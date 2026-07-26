"""Compatibility contracts for shared metadata-inspection services."""

from __future__ import annotations

import ast
import inspect
import json
import pickle
import subprocess
import sys
import typing
from collections.abc import Mapping
from pathlib import Path

import pytest

from sceneio.io import _gltf, _image_sequence, _inspection, _obj
from sceneio.io._inspectors import calibration, common, model

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "tests" / "contracts" / "io_inspection_shared_v1.json"


def _assert_lower_only_imports(source: str) -> None:
    def is_upward(name: str) -> bool:
        return name in {
            "sceneio",
            "sceneio.io",
            "sceneio.io._inspection",
            "sceneio.io.registry",
        } or name.startswith(
            (
                "sceneio.io._inspection.",
                "sceneio.io.registry.",
            )
        )

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0
            module = node.module or ""
            if module == "sceneio":
                assert all(alias.name == "_core" for alias in node.names)
                continue
            assert not is_upward(module)
            assert all(
                not is_upward(f"{module}.{alias.name}")
                for alias in node.names
            )
        elif isinstance(node, ast.Import):
            assert all(not is_upward(alias.name) for alias in node.names)


def _examples():
    return {
        "ArrayInspection": model.ArrayInspection(
            "values",
            (2, 3),
            "float32",
        ),
        "Inspection": model.Inspection(
            "npy",
            "tensor",
            128,
            shape=(2, 3),
            dtype="float32",
            count=6,
        ),
    }


def test_shared_inspection_types_preserve_exact_b2bda1d_contract():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    for name, value in _examples().items():
        value_type = type(value)
        expected = contract["types"][name]
        assert value_type.__module__ == expected["module"]
        assert value_type.__qualname__ == expected["qualname"]
        assert str(inspect.signature(value_type)) == expected["signature"]
        assert repr(value) == expected["repr"]
        assert (
            pickle.dumps(value_type, protocol=4).hex()
            == expected["type_pickle_protocol_4_hex"]
        )
        if name == "ArrayInspection":
            payload = bytes.fromhex(expected["instance_pickle_protocol_4_hex"])
            assert pickle.dumps(value, protocol=4) == payload
            restored = pickle.loads(payload)
            assert type(restored) is model.ArrayInspection
            assert restored == value
        else:
            outcome = expected["instance_pickle_protocol_4"]
            with pytest.raises(
                TypeError,
                match=outcome["message"],
            ):
                pickle.dumps(value, protocol=4)


def test_compatibility_facade_and_lower_consumers_share_exact_model_objects():
    assert _inspection.ArrayInspection is model.ArrayInspection
    assert _inspection.Inspection is model.Inspection
    assert typing.get_type_hints(model.Inspection)["metadata"] == Mapping[
        str,
        model.MetadataValue,
    ]
    assert _inspection._compiled_buffer_inspect is common._compiled_buffer_inspect
    assert calibration.Inspection is model.Inspection
    assert _obj.Inspection is model.Inspection
    assert _gltf.Inspection is model.Inspection
    assert _image_sequence.Inspection is model.Inspection


def test_common_buffer_inspector_falls_back_for_empty_file_and_releases_path(
    tmp_path,
):
    path = tmp_path / "empty"
    path.write_bytes(b"")
    seen = []

    def inspect_bytes(data):
        seen.append(data)
        return "empty"

    assert common._compiled_buffer_inspect(path, inspect_bytes) == "empty"
    assert seen == [b""]
    renamed = path.with_name("released")
    path.rename(renamed)
    renamed.unlink()


def test_lower_inspection_modules_do_not_import_compatibility_facades():
    for module in (model, common, calibration):
        _assert_lower_only_imports(inspect.getsource(module))

    for forbidden_source in (
        "import sceneio",
        "from sceneio import io",
        "from sceneio import _core, io",
        "from . import model",
    ):
        with pytest.raises(AssertionError):
            _assert_lower_only_imports(forbidden_source)


def test_facade_reload_remains_acyclic_and_preserves_shared_identity():
    code = """
import importlib

from sceneio.io import _inspection
from sceneio.io._inspectors import common, model

for _ in range(2):
    facade = importlib.reload(_inspection)
    assert facade.ArrayInspection is model.ArrayInspection
    assert facade.Inspection is model.Inspection
    assert facade._compiled_buffer_inspect is common._compiled_buffer_inspect
"""
    subprocess.run([sys.executable, "-c", code], check=True)
