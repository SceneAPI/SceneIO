"""Architecture contracts for the mesh registry/inspector family."""

from __future__ import annotations

import ast
import inspect
import subprocess
import sys
import textwrap
import tomllib
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import _core
from sceneio.io import _gltf, _inspection, _obj, registry
from sceneio.io._builtin_manifest import (
    CANONICAL_BUILTIN_IDS,
    FAMILY_MEMBERS,
)
from sceneio.io._inspectors import meshes as mesh_inspector
from sceneio.io._registry.families import meshes as mesh_family

ROOT = Path(__file__).resolve().parents[1]


def _absolute_imports_from_source(
    source: str,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    imports = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.extend((alias.name, ()) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, (node.level, node.module)
            imports.append(
                (
                    node.module or "",
                    tuple(alias.name for alias in node.names),
                )
            )
    return tuple(imports)


def _assert_core_only_sceneio_import(
    imports: tuple[tuple[str, tuple[str, ...]], ...],
) -> None:
    assert tuple(
        names for module, names in imports if module == "sceneio"
    ) == (("_core",),)


def _assert_mesh_family_imports(source: str) -> None:
    imports = _absolute_imports_from_source(source)
    _assert_core_only_sceneio_import(imports)
    assert {
        module for module, _ in imports
    } <= {
        "__future__",
        "sceneio",
        "sceneio.io._gltf",
        "sceneio.io._obj",
        "sceneio.io._usd",
        "sceneio.io._registry.adapters",
        "sceneio.io._registry.model",
    }


def test_mesh_definitions_preserve_canonical_order_and_identity():
    definitions = mesh_family.MESH_CODECS
    expected_ids = FAMILY_MEMBERS["meshes"]
    assert isinstance(definitions, tuple)
    assert tuple(codec.id for codec in definitions) == expected_ids
    start = CANONICAL_BUILTIN_IDS.index(expected_ids[0])
    stop = start + len(expected_ids)
    assert CANONICAL_BUILTIN_IDS[start:stop] == expected_ids
    assert CANONICAL_BUILTIN_IDS[start - 1] == "ksplat"
    assert CANONICAL_BUILTIN_IDS[stop] == "ply"
    assert tuple(registry.REGISTRY)[start:stop] == expected_ids
    for offset, codec in enumerate(definitions):
        assert registry.REGISTRY[codec.id] is codec
        assert registry.BUILTIN_DEFINITIONS[start + offset] is codec

    assert definitions[0].record is _core.Mesh
    assert definitions[1].record is _core.Mesh
    assert definitions[2].record is _core.Mesh
    assert definitions[3].record is _core.Mesh
    assert definitions[4].record is _core.SceneGraph
    assert definitions[5].record is _core.SceneGraph
    assert definitions[6].record is _core.SceneGraph
    assert definitions[7].record is _core.SceneGraph


def test_mesh_bespoke_adapter_and_selector_identities_are_exact():
    codecs = {codec.id: codec for codec in mesh_family.MESH_CODECS}
    assert codecs["obj"].read is _obj.read_obj
    assert codecs["obj"].write is _obj.write_obj
    assert codecs["obj"].inspect is _obj.inspect_obj
    assert codecs["obj"].container_kind == "multi_file"

    for format_id, read, write, inspect_path, read_mesh, read_primitive in (
        (
            "gltf",
            _gltf.read_gltf,
            _gltf.write_gltf,
            _gltf.inspect_gltf,
            _gltf.read_gltf_mesh,
            _gltf.read_gltf_primitive,
        ),
        (
            "glb",
            _gltf.read_glb,
            _gltf.write_glb,
            _gltf.inspect_glb,
            _gltf.read_glb_mesh,
            _gltf.read_glb_primitive,
        ),
    ):
        codec = codecs[format_id]
        assert codec.read is read
        assert codec.write is write
        assert codec.inspect is inspect_path
        assert codec.read_mesh is read_mesh
        assert codec.read_primitive is read_primitive

    assert codecs["ply_mesh"].read_faces is not None
    assert codecs["stl"].read_faces is not None
    assert codecs["off"].read_faces is not None
    assert all(
        codecs[format_id].inspect is None
        for format_id in ("ply_mesh", "stl", "off")
    )


def test_mesh_family_modules_are_lower_layer_only():
    _assert_mesh_family_imports(inspect.getsource(mesh_family))

    inspector_imports = _absolute_imports_from_source(
        inspect.getsource(mesh_inspector)
    )
    _assert_core_only_sceneio_import(inspector_imports)
    assert {
        module for module, _ in inspector_imports
    } <= {
        "__future__",
        "pathlib",
        "sceneio",
        "sceneio.io._inspectors.common",
        "sceneio.io._inspectors.model",
        "sceneio.io._ply",
    }

    for module in (mesh_family, mesh_inspector):
        source = inspect.getsource(module)
        assert "sceneio.io.registry" not in source
        assert "sceneio.io._inspection" not in source
        assert "REGISTRY" not in source
        assert "register(" not in source


def test_lower_mesh_inspectors_use_metadata_only_entry_points():
    source = inspect.getsource(mesh_inspector)
    assert "_core.read_" not in source
    assert "_core._inspect_stl" in source
    assert "_core._inspect_off" in source
    assert "parse_ply_header" in source
    assert "validate_mesh_ply_header" in source


def test_mesh_lower_import_guard_rejects_upward_relative_and_sibling_imports():
    for source in (
        "import sceneio",
        "from sceneio import io",
        "from sceneio import _core, io",
        "from sceneio.io import registry",
        "from sceneio.io._registry.families import calibration",
        "from . import meshes",
    ):
        with pytest.raises(AssertionError):
            _assert_mesh_family_imports(source)


def test_mesh_family_and_registry_reload_are_idempotent():
    code = textwrap.dedent(
        """
        import importlib

        from sceneio.io import registry
        from sceneio.io._builtin_manifest import (
            CANONICAL_BUILTIN_IDS,
            FAMILY_MEMBERS,
        )
        from sceneio.io._registry.families import meshes

        before_registry = registry.REGISTRY
        before_items = tuple(registry.REGISTRY.items())
        reloaded_family = importlib.reload(meshes)
        assert registry.REGISTRY is before_registry
        assert tuple(registry.REGISTRY.items()) == before_items
        assert all(
            registry.REGISTRY[codec.id] is not codec
            for codec in reloaded_family.MESH_CODECS
        )

        for _ in range(2):
            reloaded_registry = importlib.reload(registry)
            assert tuple(reloaded_registry.REGISTRY) == CANONICAL_BUILTIN_IDS
            assert tuple(
                reloaded_registry.REGISTRY[format_id]
                for format_id in FAMILY_MEMBERS["meshes"]
            ) == reloaded_family.MESH_CODECS
        """
    )
    subprocess.run([sys.executable, "-c", code], check=True)


@pytest.mark.parametrize(
    ("wrapper_name", "delegate_name"),
    [
        ("_inspect_ply_mesh", "_inspect_mesh_ply"),
        ("_inspect_stl", "_inspect_mesh_stl"),
        ("_inspect_off", "_inspect_mesh_off"),
    ],
)
def test_mesh_inspector_facade_preserves_historical_wrapper_signatures(
    wrapper_name,
    delegate_name,
    monkeypatch,
):
    marker = object()
    calls = []

    def inspect_family(path, datatype):
        calls.append((path, datatype))
        return marker

    monkeypatch.setattr(_inspection, delegate_name, inspect_family)
    path = Path("mesh.fixture")
    wrapper = getattr(_inspection, wrapper_name)
    assert tuple(inspect.signature(wrapper).parameters) == ("path", "datatype")
    assert wrapper(path, "mesh") is marker
    assert calls == [(path, "mesh")]


def test_repository_coverage_tracks_only_moved_mesh_inspectors():
    contract = tomllib.loads(
        (
            ROOT / "tests" / "contracts" / "repository_coverage_v1.toml"
        ).read_text(encoding="utf-8")
    )
    owners = {
        item["id"]: item["inspection_source"]
        for item in contract["codec"]
        if item["id"] in FAMILY_MEMBERS["meshes"]
    }
    assert owners == {
        "ply_mesh": "src/sceneio/io/_inspectors/meshes.py",
        "obj": "src/sceneio/io/_obj.py",
        "stl": "src/sceneio/io/_inspectors/meshes.py",
        "off": "src/sceneio/io/_inspectors/meshes.py",
        "gltf": "src/sceneio/io/_gltf.py",
        "glb": "src/sceneio/io/_gltf.py",
        "usd": "src/sceneio/io/_usd/__init__.py",
        "usdz": "src/sceneio/io/_usd/__init__.py",
    }


@pytest.mark.parametrize(
    ("format_id", "inspector", "data"),
    [
        (
            "ply_mesh",
            mesh_inspector.inspect_ply_mesh,
            b"ply\nformat ascii 1.0\n",
        ),
        ("stl", mesh_inspector.inspect_stl, b"bad"),
        ("off", mesh_inspector.inspect_off, b"OFF\n"),
    ],
)
def test_malformed_mesh_inspection_preserves_public_cause(
    tmp_path,
    format_id,
    inspector,
    data,
):
    path = tmp_path / format_id
    path.write_bytes(data)
    with pytest.raises(Exception) as lower_error:
        inspector(path, "mesh")
    with pytest.raises(sceneio.FormatError) as public_error:
        sceneio.inspect(path, format=format_id)
    cause = public_error.value.__cause__
    assert type(cause) is type(lower_error.value)
    assert str(cause) == str(lower_error.value)


def test_retained_mesh_inspections_do_not_hold_file_handles(tmp_path):
    mesh = _core.mesh(
        np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32),
        np.array([0, 3], np.uint64),
        np.array([0, 1, 2], np.uint64),
    )
    for format_id in ("ply_mesh", "stl", "off"):
        path = tmp_path / f"mesh-{format_id}"
        sceneio.write(mesh, path, format=format_id)
        info = sceneio.inspect(path, format=format_id)
        renamed = path.with_suffix(".released")
        path.rename(renamed)
        renamed.unlink()
        assert info.count == 3


def test_large_mesh_inspection_has_bounded_allocation_and_releases_path(
    tmp_path,
):
    vertices = 3_000_000
    header = f"""ply
format binary_little_endian 1.0
element vertex {vertices}
property float x
property float y
property float z
element face 0
property list uchar uint vertex_indices
end_header
""".encode()
    path = tmp_path / "large-mesh.ply"
    with path.open("wb") as stream:
        stream.write(header)
        stream.truncate(len(header) + vertices * 12)
    assert path.stat().st_size > 32 * 1024 * 1024

    tracemalloc.start()
    try:
        info = sceneio.inspect(path, format="ply_mesh")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert info.count == vertices
    assert peak < 1024 * 1024
    renamed = path.with_suffix(".released")
    path.rename(renamed)
    renamed.unlink()


def test_point_ply_inspection_ownership_remains_in_facade():
    source = inspect.getsource(mesh_inspector)
    assert "validate_mesh_ply_header" in source
    assert "validate_point_ply_header" not in source
    assert _inspection._inspect_ply.__module__ == "sceneio.io._inspection"
