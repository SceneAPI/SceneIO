"""Architecture contracts for the calibration registry/inspector family."""

from __future__ import annotations

import ast
import inspect
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from sceneio import _core
from sceneio.io import _inspection, registry
from sceneio.io._builtin_manifest import (
    CANONICAL_BUILTIN_IDS,
    FAMILY_MEMBERS,
)
from sceneio.io._inspectors import calibration as calibration_inspector
from sceneio.io._registry.families import calibration as calibration_family


def _probe_codec(format_id: str) -> registry.Codec:
    return registry.Codec(
        format_id,
        (),
        str,
        None,
        None,
        "probe",
    )


def _absolute_imports(module) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return _absolute_imports_from_source(inspect.getsource(module))


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


def test_calibration_definitions_preserve_canonical_order_and_identity():
    definitions = calibration_family.CALIBRATION_CODECS
    expected_ids = FAMILY_MEMBERS["calibration"]
    assert isinstance(definitions, tuple)
    assert tuple(codec.id for codec in definitions) == expected_ids
    start = CANONICAL_BUILTIN_IDS.index(expected_ids[0])
    stop = start + len(expected_ids)
    assert CANONICAL_BUILTIN_IDS[start:stop] == expected_ids
    assert CANONICAL_BUILTIN_IDS[start - 1] == "euroc_state"
    assert CANONICAL_BUILTIN_IDS[stop] == "g2o"
    assert tuple(registry.REGISTRY)[start:stop] == expected_ids
    for offset, codec in enumerate(definitions):
        assert registry.REGISTRY[codec.id] is codec
        assert registry.BUILTIN_DEFINITIONS[start + offset] is codec
        assert codec.record is _core.CameraRig
        assert codec.inspect is None
        assert codec.extensions == codec.filenames == ()


def test_calibration_family_modules_are_lower_layer_only():
    family_imports = _absolute_imports(calibration_family)
    _assert_core_only_sceneio_import(family_imports)
    allowed_family = {
        "__future__",
        "sceneio",
        "sceneio.io._registry.adapters",
        "sceneio.io._registry.model",
    }
    assert {module for module, _ in family_imports} <= allowed_family

    inspector_imports = _absolute_imports(calibration_inspector)
    _assert_core_only_sceneio_import(inspector_imports)
    assert {
        module for module, _ in inspector_imports
    } <= {"__future__", "collections.abc", "pathlib", "sceneio"}
    for module in (calibration_family, calibration_inspector):
        source = inspect.getsource(module)
        assert "sceneio.io.registry" not in source
        assert "sceneio.io._inspection" not in source
        assert "REGISTRY" not in source
        assert "register(" not in source


@pytest.mark.parametrize(
    "source",
    [
        "import sceneio",
        "from sceneio import io",
        "from sceneio import _core, io",
    ],
)
def test_sceneio_import_guard_rejects_public_package_imports(source):
    with pytest.raises(AssertionError):
        _assert_core_only_sceneio_import(_absolute_imports_from_source(source))


def test_calibration_inspector_table_uses_only_metadata_entry_points():
    assert {
        "opencv_yaml": _core._inspect_opencv_yaml,
        "opencv_xml": _core._inspect_opencv_xml,
        "ros_camera_info": _core._inspect_ros_camera_info,
        "kalibr": _core._inspect_kalibr,
    } == calibration_inspector._INSPECTORS


def test_calibration_family_and_registry_reload_are_idempotent():
    code = textwrap.dedent(
        """
        import importlib

        from sceneio.io import registry
        from sceneio.io._builtin_manifest import (
            CANONICAL_BUILTIN_IDS,
            FAMILY_MEMBERS,
        )
        from sceneio.io._registry.families import calibration

        before_registry = registry.REGISTRY
        before_items = tuple(registry.REGISTRY.items())
        reloaded_family = importlib.reload(calibration)
        assert registry.REGISTRY is before_registry
        assert tuple(registry.REGISTRY.items()) == before_items
        assert all(
            registry.REGISTRY[codec.id] is not codec
            for codec in reloaded_family.CALIBRATION_CODECS
        )

        for _ in range(2):
            reloaded_registry = importlib.reload(registry)
            assert tuple(reloaded_registry.REGISTRY) == CANONICAL_BUILTIN_IDS
            assert tuple(
                reloaded_registry.REGISTRY[format_id]
                for format_id in FAMILY_MEMBERS["calibration"]
            ) == reloaded_family.CALIBRATION_CODECS
        """
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_builtin_family_validation_is_atomic():
    before = tuple(registry.REGISTRY.items())
    invalid_cases = (
        ((object(),), ("probe",), TypeError),
        (
            (_probe_codec("second"), _probe_codec("first")),
            ("first", "second"),
            ValueError,
        ),
        (
            (_probe_codec("duplicate"), _probe_codec("duplicate")),
            ("duplicate", "duplicate"),
            ValueError,
        ),
        ((_probe_codec("npy"),), ("npy",), ValueError),
    )
    for definitions, expected, exception_type in invalid_cases:
        with pytest.raises(exception_type):
            registry._install_builtin_family(definitions, expected)
        assert tuple(registry.REGISTRY.items()) == before


@pytest.mark.parametrize("format_id", FAMILY_MEMBERS["calibration"])
def test_calibration_inspector_facade_injects_historical_dependencies(
    format_id,
    monkeypatch,
):
    marker = object()
    calls = []

    def inspect_family(path, selected, datatype, **dependencies):
        calls.append((path, selected, datatype, dependencies))
        return marker

    monkeypatch.setattr(
        _inspection,
        "_inspect_calibration_camera_rig",
        inspect_family,
    )
    path = Path("calibration.fixture")
    assert _inspection._inspect_camera_rig(path, format_id, "camera_rig") is marker
    assert calls == [
        (
            path,
            format_id,
            "camera_rig",
            {
                "inspection_type": _inspection.Inspection,
                "inspect_buffer": _inspection._compiled_buffer_inspect,
            },
        )
    ]
