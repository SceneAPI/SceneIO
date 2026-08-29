"""Architecture and parent-behavior contracts for the point I/O family."""

from __future__ import annotations

import ast
import dataclasses
import gc
import hashlib
import inspect
import json
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
from sceneio.io import _inspection, registry
from sceneio.io._builtin_manifest import (
    CANONICAL_BUILTIN_IDS,
    FAMILY_MEMBERS,
)
from sceneio.io._inspectors import points as point_inspector
from sceneio.io._registry.families import points as point_family

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "tests" / "contracts" / "io_point_family_v1.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
POINT_IDS = tuple(CONTRACT["family_ids"])
ALL_POINT_IDS = FAMILY_MEMBERS["points"]


def _absolute_imports(source: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
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


def _point_cloud(count: int = 4):
    if count == 4:
        positions = np.array(
            [
                [-1.25, 2.5, 0.0],
                [3.0, -4.5, 6.25],
                [7.5, 8.0, -9.0],
                [10.0, 11.5, 12.25],
            ],
            dtype=np.float32,
        )
    else:
        positions = (
            np.arange(count * 3, dtype=np.float32).reshape(count, 3) / 10
        )
    return _core.point_cloud(positions)


def _write_valid_points(
    root: Path,
    count: int = 4,
    format_ids: tuple[str, ...] = POINT_IDS,
) -> dict[str, Path]:
    cloud = _point_cloud(count)
    paths = {}
    for format_id in format_ids:
        path = root / f"valid.{format_id}"
        sceneio.write(cloud, path, format=format_id)
        paths[format_id] = path
    return paths


def _normalized_inspection(info) -> dict[str, object]:
    return json.loads(
        json.dumps(
            {
                "format": info.format,
                "datatype": info.datatype,
                "byte_size": info.byte_size,
                "shape": info.shape,
                "dtype": info.dtype,
                "channels": info.channels,
                "count": info.count,
                "arrays": [
                    {
                        "name": value.name,
                        "shape": value.shape,
                        "dtype": value.dtype,
                    }
                    for value in info.arrays
                ],
                "metadata": dict(info.metadata),
            }
        )
    )


def test_point_definitions_preserve_noncontiguous_order_and_identity():
    definitions = registry.POINT_CODECS
    assert isinstance(definitions, tuple)
    assert tuple(codec.id for codec in definitions) == ALL_POINT_IDS
    assert tuple(CONTRACT["family_ids"]) == POINT_IDS
    assert tuple(registry.REGISTRY) == CANONICAL_BUILTIN_IDS
    assert tuple(
        sorted(POINT_IDS, key=CANONICAL_BUILTIN_IDS.index)
    ) == POINT_IDS
    for codec in definitions:
        position = CANONICAL_BUILTIN_IDS.index(codec.id)
        assert registry.REGISTRY[codec.id] is codec
        assert registry.BUILTIN_DEFINITIONS[position] is codec
        if codec.id == "e57":
            assert codec.inspect is not None
        else:
            assert codec.inspect is None


def test_point_family_is_staged_once_and_not_defined_inline():
    source = inspect.getsource(registry)
    tree = ast.parse(source)
    point_staging = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_define_builtin_family"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "points"
    ]
    assert len(point_staging) == 1
    assert source.count('_define_builtin_family("points", POINT_CODECS)') == 1
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Codec"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            assert node.args[0].value not in ALL_POINT_IDS


@pytest.mark.parametrize("format_id", POINT_IDS)
def test_point_adapter_closures_preserve_exact_native_targets(format_id):
    codec = registry.REGISTRY[format_id]
    assert inspect.getclosurevars(codec.read).nonlocals == {
        "fn": getattr(_core, f"read_{format_id}")
    }
    assert inspect.getclosurevars(codec.write).nonlocals == {
        "fn": getattr(_core, f"write_{format_id}"),
        "prepare": None,
    }
    assert inspect.getclosurevars(codec.read_points).nonlocals == {
        "fn": getattr(_core, f"read_{format_id}_points")
    }


def test_point_family_modules_are_lower_layer_only():
    family_imports = _absolute_imports(inspect.getsource(point_family))
    assert {
        module for module, _ in family_imports
    } <= {
        "__future__",
        "sceneio",
        "sceneio.io._e57",
        "sceneio.io._registry.adapters",
        "sceneio.io._registry.model",
    }
    inspector_imports = _absolute_imports(inspect.getsource(point_inspector))
    assert {
        module for module, _ in inspector_imports
    } <= {
        "__future__",
        "math",
        "pathlib",
        "sceneio",
        "sceneio.io._inspectors.common",
        "sceneio.io._inspectors.model",
        "sceneio.io._pcd",
        "sceneio.io._ply",
        "struct",
    }
    for module in (point_family, point_inspector):
        source = inspect.getsource(module)
        assert "sceneio.io.registry" not in source
        assert "sceneio.io._inspection" not in source
        assert "sceneio.io._registry.assembly" not in source
        assert "REGISTRY" not in source
        assert "register(" not in source
    inspector_source = inspect.getsource(point_inspector)
    for format_id in POINT_IDS:
        assert f"_core.read_{format_id}" not in inspector_source
        assert f"_core.write_{format_id}" not in inspector_source


def test_point_family_reload_is_inert_and_registry_reload_is_exact():
    code = textwrap.dedent(
        """
        import importlib

        from sceneio.io import registry
        from sceneio.io._builtin_manifest import (
            CANONICAL_BUILTIN_IDS,
            FAMILY_MEMBERS,
        )
        from sceneio.io._registry.families import points

        before_registry = registry.REGISTRY
        before_items = tuple(registry.REGISTRY.items())
        before_point_codecs = registry.POINT_CODECS
        reloaded_family = importlib.reload(points)
        assert registry.REGISTRY is before_registry
        assert tuple(registry.REGISTRY.items()) == before_items
        assert registry.POINT_CODECS is before_point_codecs
        assert tuple(codec.id for codec in reloaded_family.POINT_CODECS) == (
            FAMILY_MEMBERS["points"]
        )
        assert all(
            registry.REGISTRY[codec.id] is not codec
            for codec in reloaded_family.POINT_CODECS
        )

        for _ in range(2):
            reloaded_registry = importlib.reload(registry)
            assert tuple(reloaded_registry.REGISTRY) == CANONICAL_BUILTIN_IDS
            assert tuple(
                codec.id for codec in reloaded_registry.POINT_CODECS
            ) == FAMILY_MEMBERS["points"]
            for codec in reloaded_registry.POINT_CODECS:
                assert reloaded_registry.REGISTRY[codec.id] is codec
        """
    )
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)


@pytest.mark.parametrize(
    ("wrapper_name", "delegate_name"),
    [
        ("_inspect_ply", "_inspect_point_ply"),
        ("_inspect_pcd", "_inspect_point_pcd"),
        ("_inspect_xyz", "_inspect_point_xyz"),
        ("_inspect_pts", "_inspect_point_pts"),
        ("_inspect_las", "_inspect_point_las"),
        ("_inspect_laz", "_inspect_point_laz"),
    ],
)
def test_point_inspector_facade_preserves_wrapper_signatures(
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
    path = Path("point.fixture")
    wrapper = getattr(_inspection, wrapper_name)
    assert tuple(inspect.signature(wrapper).parameters) == ("path", "datatype")
    assert wrapper(path, "point_cloud") is marker
    assert calls == [(path, "point_cloud")]


def test_repository_coverage_tracks_all_point_inspectors():
    contract = tomllib.loads(
        (
            ROOT / "tests" / "contracts" / "repository_coverage_v1.toml"
        ).read_text(encoding="utf-8")
    )
    owners = {
        item["id"]: item["inspection_source"]
        for item in contract["codec"]
        if item["id"] in ALL_POINT_IDS
    }
    assert owners == {
        format_id: "src/sceneio/io/_inspectors/points.py"
        for format_id in POINT_IDS
    } | {
        "e57": "src/sceneio/io/_e57.py",
    }


@pytest.mark.parametrize("format_id", POINT_IDS)
def test_point_inspection_matches_parent_contract_and_full_read(
    tmp_path,
    format_id,
):
    expected = CONTRACT["valid"][format_id]
    path = _write_valid_points(tmp_path, format_ids=(format_id,))[format_id]
    assert path.stat().st_size == expected["byte_size"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected["sha256"]

    lower = getattr(point_inspector, f"inspect_{format_id}")(
        path,
        registry.REGISTRY[format_id].datatype,
    )
    public = sceneio.inspect(path, format=format_id)
    assert _normalized_inspection(lower) == expected["inspection"]
    assert _normalized_inspection(public) == expected["inspection"]

    full = sceneio.read(path, format=format_id)
    assert list(full.positions.shape) == expected["inspection"]["shape"]
    assert str(full.positions.dtype) == expected["inspection"]["dtype"]
    assert len(full.positions) == expected["inspection"]["count"]


@pytest.mark.parametrize("format_id", POINT_IDS)
def test_malformed_point_inspection_matches_parent_contract(
    tmp_path,
    format_id,
):
    expected = CONTRACT["malformed"][format_id]
    path = tmp_path / f"bad.{format_id}"
    path.write_bytes(b"bad")
    inspector = getattr(point_inspector, f"inspect_{format_id}")
    with pytest.raises(Exception) as lower_error:
        inspector(path, registry.REGISTRY[format_id].datatype)
    assert type(lower_error.value).__name__ == expected["cause_type"]
    assert str(lower_error.value) == expected["cause_message"]

    with pytest.raises(sceneio.FormatError) as public_error:
        sceneio.inspect(path, format=format_id)
    cause = public_error.value.__cause__
    assert type(cause).__name__ == expected["cause_type"]
    assert str(cause) == expected["cause_message"]


def test_public_point_inspection_does_not_call_full_decoders(
    tmp_path,
    monkeypatch,
):
    paths = _write_valid_points(tmp_path)
    original = {format_id: registry.REGISTRY[format_id] for format_id in POINT_IDS}

    def fail(*_args, **_kwargs):
        raise AssertionError("full point decoder called during inspection")

    for format_id, codec in original.items():
        registry.REGISTRY[format_id] = dataclasses.replace(codec, read=fail)
        monkeypatch.setattr(_core, f"read_{format_id}", fail)
    try:
        for format_id, path in paths.items():
            assert sceneio.inspect(path, format=format_id).format == format_id
    finally:
        registry.REGISTRY.update(original)


@pytest.mark.parametrize("format_id", POINT_IDS)
def test_point_partial_read_matches_full_slice_and_releases_path(
    tmp_path,
    format_id,
):
    path = _write_valid_points(tmp_path, format_ids=(format_id,))[format_id]
    full = sceneio.read(path, format=format_id)
    selected = sceneio.read_partial(
        path,
        format=format_id,
        points=(1, 3),
    )
    assert np.array_equal(selected.positions, full.positions[1:3])
    assert selected.coordinate_frame == full.coordinate_frame
    assert selected.scale_to_meters == full.scale_to_meters

    released = path.with_suffix(path.suffix + ".released")
    path.rename(released)
    released.unlink()
    assert np.array_equal(selected.positions, full.positions[1:3])


@pytest.mark.parametrize("format_id", POINT_IDS)
def test_retained_inspection_exception_releases_point_path(
    tmp_path,
    format_id,
):
    path = tmp_path / f"bad.{format_id}"
    path.write_bytes(b"bad")
    retained = None
    with pytest.raises(sceneio.FormatError) as captured:
        sceneio.inspect(path, format=format_id)
    retained = captured.value
    path.unlink()
    assert retained.__cause__ is not None


@pytest.mark.parametrize("format_id", POINT_IDS)
def test_large_point_inspection_is_bounded_and_releases_path(
    tmp_path,
    format_id,
):
    path = _write_valid_points(
        tmp_path,
        count=50_000,
        format_ids=(format_id,),
    )[format_id]
    gc.collect()
    tracemalloc.start()
    try:
        info = sceneio.inspect(path, format=format_id)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 2 * 1024 * 1024, (format_id, peak)

    renamed = path.with_suffix(path.suffix + ".released")
    path.rename(renamed)
    renamed.unlink()
    assert info.count == 50_000
