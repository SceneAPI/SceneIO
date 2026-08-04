"""Repository-owned codec manifest and extension-boundary checks."""

from __future__ import annotations

import ast
import importlib
import inspect
import json
import subprocess
import sys
import textwrap
import tomllib
from dataclasses import replace
from functools import partial
from pathlib import Path

import pytest

import sceneio
import sceneio.io
from sceneio import _core
from sceneio.io import registry
from sceneio.io._builtin_manifest import (
    BUILTIN_OWNERSHIP,
    CANONICAL_BUILTIN_IDS,
    FAMILY_MEMBERS,
)
from sceneio.io._inspection import inspect_path

ROOT = Path(__file__).resolve().parents[1]


def _resolve_python_symbol(dotted: str):
    module_name, _, name = dotted.rpartition(".")
    return getattr(importlib.import_module(module_name), name)


def _implementation_callable(value):
    while isinstance(value, partial):
        value = value.func
    return value


def test_builtin_manifest_is_exact_and_preserves_runtime_identity():
    assert len(CANONICAL_BUILTIN_IDS) == 74
    assert tuple(registry.REGISTRY) == CANONICAL_BUILTIN_IDS
    assert tuple(codec.id for codec in registry.BUILTIN_DEFINITIONS) == (
        CANONICAL_BUILTIN_IDS
    )
    assert all(
        registry.REGISTRY[codec.id] is codec
        for codec in registry.BUILTIN_DEFINITIONS
    )
    assert sceneio.io.REGISTRY is registry.REGISTRY


def test_families_partition_builtins_without_changing_dispatch_order():
    family_ids = [
        format_id for members in FAMILY_MEMBERS.values() for format_id in members
    ]
    assert len(family_ids) == len(set(family_ids)) == 74
    assert set(family_ids) == set(CANONICAL_BUILTIN_IDS)
    assert set(BUILTIN_OWNERSHIP) == set(CANONICAL_BUILTIN_IDS)
    for family, members in FAMILY_MEMBERS.items():
        assert members
        assert all(BUILTIN_OWNERSHIP[item].family == family for item in members)


def test_ownership_symbols_resolve_to_current_implementations():
    operation_fields = (
        "read",
        "write",
        "inspect",
        "read_window",
        "read_points",
        "read_faces",
        "read_mesh",
        "read_primitive",
        "read_states",
        "read_frames",
        "read_image",
        "read_pair",
        "read_tensors",
        "read_slices",
    )
    for ownership in BUILTIN_OWNERSHIP.values():
        assert ownership.implementation_owner in {"native", "python", "hybrid"}
        if ownership.implementation_owner != "python":
            assert ownership.native_symbols
        for symbol in ownership.native_symbols:
            assert hasattr(_core, symbol), f"{ownership.id}: _core.{symbol}"
        python_callables = {
            _resolve_python_symbol(symbol) for symbol in ownership.python_symbols
        }
        assert all(callable(value) for value in python_callables)
        runtime_callables = {
            _implementation_callable(getattr(registry.REGISTRY[ownership.id], field))
            for field in operation_fields
            if getattr(registry.REGISTRY[ownership.id], field) is not None
        }
        assert python_callables <= runtime_callables
        if ownership.implementation_owner in {"hybrid", "python"}:
            assert python_callables


def test_image_sequence_frame_dependencies_are_injected_at_runtime():
    from sceneio.io import _frame_access
    from sceneio.io import _image_sequence as adapter

    codec = registry.REGISTRY["image_sequence"]
    access = registry._IMAGE_FRAME_ACCESS
    assert access.image_extensions() == frozenset(
        extension
        for candidate in registry.REGISTRY.values()
        if candidate.record is _core.Image
        for extension in candidate.extensions
    )
    for field, implementation, parameters in (
        ("read", adapter.read_image_sequence_directory, ("path",)),
        (
            "write",
            adapter.write_image_sequence_directory,
            ("sequence", "path"),
        ),
        ("inspect", adapter.inspect_image_sequence_directory, ("path",)),
        (
            "read_frames",
            adapter.read_image_sequence_directory_frames,
            ("path", "start", "stop"),
        ),
    ):
        bound = getattr(codec, field)
        assert isinstance(bound, partial)
        assert bound.func is implementation
        assert bound.args == (access,)
        assert not bound.keywords
        assert tuple(inspect.signature(bound).parameters) == parameters
        with pytest.raises(TypeError, match="multiple values for argument 'frame_access'"):
            bound(*([None] * len(parameters)), frame_access=access)

    adapter_source = inspect.getsource(adapter)
    assert "from sceneio.io.registry import" not in adapter_source
    assert "from sceneio.io import inspect" not in adapter_source
    frame_access_source = inspect.getsource(_frame_access)
    assert "from sceneio" not in frame_access_source
    assert "import sceneio" not in frame_access_source
    assert "REGISTRY" not in frame_access_source

    code = textwrap.dedent(
        """
        import builtins
        import tempfile
        from pathlib import Path

        from sceneio.io import _image_sequence as adapter
        from sceneio.io._frame_access import ImageFrameAccess
        from sceneio.io._inspection import Inspection

        root = Path(tempfile.mkdtemp())
        frame = root / "frame.PGM"
        frame.write_bytes(b"fixture")
        calls = []

        def inspect_frame(path):
            calls.append(path)
            return Inspection(
                format="netpbm",
                datatype="image",
                byte_size=7,
                shape=(2, 3, 1),
                dtype="uint8",
                channels=1,
            )

        access = ImageFrameAccess(lambda: frozenset({".PGM"}), inspect_frame)
        original_import = builtins.__import__

        def reject_upward_import(name, *args, **kwargs):
            if name in {"sceneio.io", "sceneio.io.registry"}:
                raise AssertionError(f"unexpected upward import: {name}")
            return original_import(name, *args, **kwargs)

        builtins.__import__ = reject_upward_import
        try:
            assert adapter._image_extensions(access) == frozenset({".pgm"})
            assert adapter._frame_metadata([frame], access) == (
                2,
                3,
                1,
                "uint8",
            )
        finally:
            builtins.__import__ = original_import
        assert calls == [frame]
        """
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_third_party_registration_is_outside_builtin_completeness_boundary(
    tmp_path,
):
    extension = registry.Codec(
        "third_party_contract_probe",
        (".contract-probe", "not-dotted"),
        lambda path: path,
        None,
        record=_core.Image,
        datatype="image",
    )
    before = registry.REGISTRY
    try:
        registry.register(extension)
        assert registry.REGISTRY is before
        assert registry.REGISTRY[extension.id] is extension
        assert extension.id in sceneio.codecs()
        assert extension.id not in CANONICAL_BUILTIN_IDS
        assert ".contract-probe" in registry._IMAGE_FRAME_ACCESS.image_extensions()
        sequence_path = tmp_path / "sequence"
        sequence_path.mkdir()
        (sequence_path / "frame.pgm").write_bytes(b"P5\n1 1\n255\n\x07")
        sequence = sceneio.read(sequence_path, format="image_sequence")
        assert sequence.num_frames == 1
        assert sequence.width == sequence.height == sequence.channels == 1
        assert tuple(codec.id for codec in registry.BUILTIN_DEFINITIONS) == (
            CANONICAL_BUILTIN_IDS
        )
    finally:
        assert registry.REGISTRY.pop(extension.id) is extension
    assert ".contract-probe" not in registry._IMAGE_FRAME_ACCESS.image_extensions()
    assert "not-dotted" not in registry._IMAGE_FRAME_ACCESS.image_extensions()


def test_duplicate_registration_keeps_existing_error_contract():
    with pytest.raises(ValueError, match=r"^codec id already registered: 'npy'$"):
        registry.register(registry.REGISTRY["npy"])


def test_repository_coverage_manifest_is_complete_and_resolvable():
    contract_path = ROOT / "tests" / "contracts" / "repository_coverage_v1.toml"
    contract = tomllib.loads(contract_path.read_text(encoding="utf-8"))
    codecs = contract["codec"]
    assert contract["builtins"] == len(CANONICAL_BUILTIN_IDS)
    assert tuple(item["id"] for item in codecs) == CANONICAL_BUILTIN_IDS
    assert len({item["id"] for item in codecs}) == 74

    wheel_smoke = importlib.import_module("sceneio._wheel_smoke")
    benchmark_contract = json.loads(
        (ROOT / "tests" / "contracts" / "bench_io_v1.json").read_text(
            encoding="utf-8"
        )
    )
    benchmark_ids = set(benchmark_contract["result_order"])
    coverage_document = (ROOT / "docs" / "format_coverage.md").read_text(
        encoding="utf-8"
    )
    capability_rows = coverage_document.split(
        "<!-- sceneio-capability-rows:start -->\n", 1
    )[1].split("\n<!-- sceneio-capability-rows:end -->", 1)[0]
    for item in codecs:
        source_suites = (
            item["source_suite"],
            *item.get("additional_source_suites", ()),
        )
        for source_suite in source_suites:
            source_path = ROOT / source_suite
            assert source_path.is_file()
            token = item.get("source_case_token", item["id"])
            assert token in source_path.read_text(encoding="utf-8").lower()
        assert (ROOT / item["inspection_source"]).is_file()
        assert item["benchmark_case"] == item["id"] in benchmark_ids
        codec = registry.REGISTRY[item["id"]]
        if codec.inspect is None:
            try:
                inspect_path(
                    ROOT / "build" / "__missing_r1_inspection_fixture__",
                    item["id"],
                    codec.datatype,
                )
            except Exception as exc:
                if "does not provide metadata inspection" in str(exc):
                    raise AssertionError(
                        f"{item['id']} is absent from inspection dispatch"
                    ) from exc
        assert "wheel_smoke_exemption" not in item
        helper = getattr(wheel_smoke, item["wheel_smoke_case"])
        assert callable(helper)
        assert wheel_smoke._SMOKE_RUNNERS[item["id"]] is helper
        assert item["documentation_row"] == "docs/format_coverage.md"
        assert f"| `{item['id']}` |" in capability_rows
    assert tuple(wheel_smoke._SMOKE_RUNNERS) == CANONICAL_BUILTIN_IDS
    assert wheel_smoke._SMOKE_EXEMPTIONS == {}


def test_complete_installed_wheel_smoke_is_manifest_driven(tmp_path):
    wheel_smoke = importlib.import_module("sceneio._wheel_smoke")
    definitions = tuple(registry.BUILTIN_DEFINITIONS)
    expected_ids = tuple(codec.id for codec in definitions)
    expected_plan = []
    for codec in definitions:
        runner = wheel_smoke._SMOKE_RUNNERS[codec.id]
        if runner not in expected_plan:
            expected_plan.append(runner)
    assert wheel_smoke._smoke_runner_plan() == tuple(expected_plan)

    public_operations = (
        sceneio.write,
        sceneio.read,
        sceneio.inspect,
        sceneio.read_partial,
    )
    observed = wheel_smoke._run_manifest_smoke(tmp_path)
    assert tuple(observed) == expected_ids
    for codec in definitions:
        assert observed[codec.id] == frozenset(
            wheel_smoke._expected_smoke_properties(codec)
        )
    assert (
        sceneio.write,
        sceneio.read,
        sceneio.inspect,
        sceneio.read_partial,
    ) == public_operations


def test_installed_wheel_smoke_rejects_missing_property_and_manifest_drift(
    monkeypatch,
):
    wheel_smoke = importlib.import_module("sceneio._wheel_smoke")
    observations = {
        codec.id: wheel_smoke._expected_smoke_properties(codec)
        for codec in registry.BUILTIN_DEFINITIONS
    }
    observations["webp"].remove("selector:window")
    with pytest.raises(
        AssertionError,
        match=r"webp:selector:window",
    ):
        wheel_smoke._validate_smoke_observations(observations)

    definitions = registry.BUILTIN_DEFINITIONS
    monkeypatch.setattr(registry, "BUILTIN_DEFINITIONS", definitions[:-1])
    with pytest.raises(
        AssertionError,
        match="runners differ from installed built-in definitions",
    ):
        wheel_smoke._smoke_runner_plan()


def test_installed_wheel_smoke_stream_properties_follow_capabilities():
    wheel_smoke = importlib.import_module("sceneio._wheel_smoke")
    npy = registry.REGISTRY["npy"]

    non_streaming = replace(
        npy,
        streams_read=False,
        streams_write=False,
    )
    assert wheel_smoke._expected_smoke_properties(non_streaming) == {
        "coordinates",
        "read",
        "write",
        "inspect",
    }

    read_streaming = replace(
        npy,
        write=None,
        streams_read=True,
        streams_write=False,
    )
    assert wheel_smoke._expected_smoke_properties(read_streaming) == {
        "coordinates",
        "read",
        "inspect",
        "stream_read",
    }

    assert wheel_smoke._expected_smoke_properties(npy) == {
        "coordinates",
        "read",
        "write",
        "inspect",
        "stream_read",
        "stream_write",
    }


def test_splat_wheel_smoke_invokes_each_family_helper_once():
    wheel_smoke = importlib.import_module("sceneio._wheel_smoke")
    source = textwrap.dedent(inspect.getsource(wheel_smoke._splats))
    calls = [
        node.func.id
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id.startswith("_")
    ]
    assert calls == [
        "_gaussian_ply",
        "_compressed_ply",
        "_sog",
        "_ksplat",
        "_spz",
        "_splat",
    ]
