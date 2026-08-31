"""Contracts for atomic built-in codec assembly and publication."""

from __future__ import annotations

import ast
import copy
import functools
import hashlib
import inspect
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from bench import compare_io_structure
from sceneio.io import registry
from sceneio.io._builtin_manifest import (
    CANONICAL_BUILTIN_IDS,
    FAMILY_MEMBERS,
)
from sceneio.io._frame_access import ImageFrameAccess
from sceneio.io._registry import assembly
from sceneio.io._registry.families.calibration import CALIBRATION_CODECS
from sceneio.io._registry.model import Codec

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads(
    (ROOT / "tests/contracts/io_registry_assembly_v1.json").read_text(
        encoding="utf-8"
    )
)
CODEC_SOURCE_PATHS = (
    "src/sceneio/io/registry.py",
    "src/sceneio/io/_registry/families/arrays.py",
    "src/sceneio/io/_registry/families/calibration.py",
    "src/sceneio/io/_registry/families/containers.py",
    "src/sceneio/io/_registry/families/datasets.py",
    "src/sceneio/io/_registry/families/dense.py",
    "src/sceneio/io/_registry/families/images.py",
    "src/sceneio/io/_registry/families/meshes.py",
    "src/sceneio/io/_registry/families/points.py",
    "src/sceneio/io/_registry/families/reconstruction.py",
    "src/sceneio/io/_registry/families/sequences.py",
    "src/sceneio/io/_registry/families/splats.py",
)


def _identity(value):
    return value


def _codec(format_id: str) -> Codec:
    return Codec(format_id, (), _identity, None, None, "probe")


class _NormalizeFrameAccess(ast.NodeTransformer):
    def visit_Name(self, node: ast.Name) -> ast.Name:
        replacements = CONTRACT["codec_ast"]["normalized_names"]
        if node.id in replacements:
            node.id = replacements[node.id]
        return node


def _codec_ast_hashes() -> dict[str, str]:
    hashes = {}
    for relative in CODEC_SOURCE_PATHS:
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Codec"
            ):
                assert node.args
                assert isinstance(node.args[0], ast.Constant)
                assert isinstance(node.args[0].value, str)
                assert node.args[0].value not in hashes
                normalized = _NormalizeFrameAccess().visit(copy.deepcopy(node))
                payload = ast.dump(
                    normalized,
                    annotate_fields=True,
                    include_attributes=False,
                )
                hashes[node.args[0].value] = hashlib.sha256(
                    payload.encode()
                ).hexdigest()
    return hashes


def _callable_name(value) -> dict[str, str]:
    return {
        "module": getattr(value, "__module__", type(value).__module__),
        "qualname": getattr(value, "__qualname__", type(value).__qualname__),
    }


def _describe_operation(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"kind": "bytes", "hex": value.hex()}
    if isinstance(value, tuple):
        return {
            "kind": "tuple",
            "items": [_describe_operation(item) for item in value],
        }
    if isinstance(value, list):
        return {
            "kind": "list",
            "items": [_describe_operation(item) for item in value],
        }
    if isinstance(value, dict):
        items = [
            (_describe_operation(key), _describe_operation(item))
            for key, item in value.items()
        ]
        items.sort(
            key=lambda pair: json.dumps(
                pair[0],
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return {"kind": "dict", "items": items}
    if isinstance(value, functools.partial):
        return {
            "kind": "partial",
            "func": _describe_operation(value.func),
            "args": _describe_operation(value.args),
            "keywords": _describe_operation(value.keywords or {}),
        }
    if isinstance(value, ImageFrameAccess):
        return {
            "kind": "ImageFrameAccess",
            "extensions": _describe_operation(value.extensions),
            "inspect": _describe_operation(value.inspect),
        }
    if inspect.ismethod(value):
        return {
            "kind": "bound_method",
            "func": _describe_operation(value.__func__),
            "owner": _describe_operation(type(value.__self__)),
        }
    if isinstance(value, type):
        return {"kind": "type", **_callable_name(value)}
    if inspect.isfunction(value):
        cells = []
        if value.__closure__:
            for name, cell in zip(
                value.__code__.co_freevars,
                value.__closure__,
                strict=True,
            ):
                try:
                    cell_value = cell.cell_contents
                except ValueError:
                    cell_value = {"kind": "empty_cell"}
                cells.append([name, _describe_operation(cell_value)])
        return {
            "kind": "function",
            **_callable_name(value),
            "closure": cells,
        }
    if callable(value):
        return {"kind": "callable", **_callable_name(value)}
    raise TypeError(f"unsupported operation descriptor value: {type(value)!r}")


def _operation_hashes() -> dict[str, dict[str, str]]:
    fields = CONTRACT["operation_descriptors"]["fields"]
    hashes = {}
    for codec in registry.BUILTIN_DEFINITIONS:
        operations = {}
        for field in fields:
            value = getattr(codec, field)
            if value is not None:
                payload = json.dumps(
                    _describe_operation(value),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                operations[field] = hashlib.sha256(payload.encode()).hexdigest()
        hashes[codec.id] = operations
    return hashes


def test_parent_codec_definitions_remain_structurally_identical():
    assert CONTRACT["schema_version"] == 1
    assert CONTRACT["parent"] == {
        "commit": "14bf53b45d66c427277948b16c4aca3765e7142a",
        "tree": "fcb64bee4f4fe782e027fe8e1b0505094c57dfdf",
    }
    expected = CONTRACT["codec_ast"]["hashes"]
    assert tuple(expected) == CANONICAL_BUILTIN_IDS
    assert _codec_ast_hashes() == expected


def test_parent_operation_bindings_remain_identical():
    assert CONTRACT["operation_descriptors"]["algorithm_version"] == 1
    expected = CONTRACT["operation_descriptors"]["hashes"]
    assert tuple(expected) == CANONICAL_BUILTIN_IDS
    assert _operation_hashes() == expected


def test_builder_failure_is_recoverable_and_success_is_idempotent():
    builder = assembly.BuiltinAssembly(("first", "second"))
    first = _codec("first")
    second = _codec("second")

    assert builder.add_codec(first) is first
    with pytest.raises(ValueError, match=r"missing=\('second',\)"):
        builder.finalize()
    with pytest.raises(ValueError, match=r"already staged: 'first'"):
        builder.add_codec(first)
    assert builder.add_codec(second) is second

    definitions = builder.finalize()
    assert definitions == (first, second)
    assert builder.finalize() is definitions
    with pytest.raises(RuntimeError, match="assembly is finalized"):
        builder.add_codec(_codec("first"))
    with pytest.raises(RuntimeError, match="assembly is finalized"):
        builder.add_family("calibration", CALIBRATION_CODECS)


def test_builder_rejects_unknown_and_non_exact_codec_types_without_progress():
    class Duck:
        id = "first"

    class CodecSubclass(Codec):
        pass

    for value, error in (
        (Duck(), TypeError),
        (
            CodecSubclass("first", (), _identity, None, None, "probe"),
            TypeError,
        ),
        (_codec("unknown"), ValueError),
    ):
        builder = assembly.BuiltinAssembly(("first",))
        with pytest.raises(error):
            builder.add_codec(value)
        with pytest.raises(ValueError, match=r"missing=\('first',\)"):
            builder.finalize()
        expected = _codec("first")
        builder.add_codec(expected)
        assert builder.finalize() == (expected,)


def test_family_staging_is_exact_atomic_and_recoverable():
    expected_ids = FAMILY_MEMBERS["calibration"]

    builder = assembly.BuiltinAssembly(expected_ids)
    with pytest.raises(ValueError, match="do not match"):
        builder.add_family("calibration", tuple(reversed(CALIBRATION_CODECS)))
    assert builder.add_family("calibration", CALIBRATION_CODECS) == (
        CALIBRATION_CODECS
    )
    assert builder.finalize() == CALIBRATION_CODECS

    builder = assembly.BuiltinAssembly(expected_ids)
    invalid = (*CALIBRATION_CODECS[:-1], object())
    with pytest.raises(TypeError, match="family entries"):
        builder.add_family("calibration", invalid)
    assert builder.add_family("calibration", CALIBRATION_CODECS)
    assert builder.finalize() == CALIBRATION_CODECS

    builder = assembly.BuiltinAssembly(expected_ids)
    duplicate = (
        CALIBRATION_CODECS[0],
        CALIBRATION_CODECS[0],
        *CALIBRATION_CODECS[2:],
    )
    with pytest.raises(ValueError, match="family ids must be unique"):
        builder.add_family("calibration", duplicate)
    assert builder.add_family("calibration", CALIBRATION_CODECS)
    assert builder.finalize() == CALIBRATION_CODECS

    builder = assembly.BuiltinAssembly(expected_ids)
    assert builder.add_codec(CALIBRATION_CODECS[1]) is CALIBRATION_CODECS[1]
    with pytest.raises(ValueError, match="already staged"):
        builder.add_family("calibration", CALIBRATION_CODECS)
    assert builder.add_codec(CALIBRATION_CODECS[0]) is CALIBRATION_CODECS[0]
    for codec in CALIBRATION_CODECS[2:]:
        assert builder.add_codec(codec) is codec
    assert builder.finalize() == CALIBRATION_CODECS

    builder = assembly.BuiltinAssembly(expected_ids)
    with pytest.raises(ValueError, match="unknown built-in codec family"):
        builder.add_family("missing", CALIBRATION_CODECS)
    assert builder.add_family("calibration", CALIBRATION_CODECS)
    assert builder.finalize() == CALIBRATION_CODECS


def test_publication_is_one_update_and_rejections_leave_target_unchanged():
    class FailingUpdateDict(dict):
        calls = 0

        def update(self, *args, **kwargs):
            self.calls += 1
            self["partial"] = _codec("partial")
            raise RuntimeError("injected update failure")

    target = {}
    target_id = id(target)
    assert (
        assembly.publish_builtin_definitions(
            target,
            registry.BUILTIN_DEFINITIONS,
        )
        is None
    )
    assert id(target) == target_id
    assert tuple(target.items()) == tuple(registry.REGISTRY.items())

    seeded = {"preexisting": _codec("preexisting")}
    before = tuple(seeded.items())
    seeded_id = id(seeded)
    with pytest.raises(ValueError, match="must be empty"):
        assembly.publish_builtin_definitions(
            seeded,
            registry.BUILTIN_DEFINITIONS,
        )
    assert id(seeded) == seeded_id
    assert tuple(seeded.items()) == before

    invalid = {}
    with pytest.raises(ValueError, match="do not match"):
        assembly.publish_builtin_definitions(
            invalid,
            tuple(reversed(registry.BUILTIN_DEFINITIONS)),
        )
    assert not invalid

    failing = FailingUpdateDict()
    with pytest.raises(TypeError, match="must be an exact dict"):
        assembly.publish_builtin_definitions(
            failing,
            registry.BUILTIN_DEFINITIONS,
        )
    assert not failing
    assert failing.calls == 0


def test_public_registration_and_family_installer_keep_canonical_behavior():
    class Duck:
        id = "assembly_duck_probe"

    class CodecSubclass(Codec):
        pass

    duck = Duck()
    subclass = CodecSubclass(
        "assembly_subclass_probe",
        (),
        _identity,
        None,
        None,
        "probe",
    )
    registry_id = id(registry.REGISTRY)
    before = tuple(registry.REGISTRY.items())
    try:
        assert registry.register(duck) is duck
        assert registry.register(subclass) is subclass
        assert registry.REGISTRY[duck.id] is duck
        assert registry.REGISTRY[subclass.id] is subclass
        with pytest.raises(ValueError, match="already registered"):
            registry.register(duck)
    finally:
        registry.REGISTRY.pop(duck.id, None)
        registry.REGISTRY.pop(subclass.id, None)
    assert id(registry.REGISTRY) == registry_id
    assert tuple(registry.REGISTRY.items()) == before

    family = (_codec("runtime-family-a"), _codec("runtime-family-b"))
    assert registry._install_builtin_family(
        family,
        ("runtime-family-a", "runtime-family-b"),
    ) is None
    try:
        assert registry.REGISTRY["runtime-family-a"] is family[0]
        assert registry.REGISTRY["runtime-family-b"] is family[1]
    finally:
        registry.REGISTRY.pop("runtime-family-a")
        registry.REGISTRY.pop("runtime-family-b")
    assert tuple(registry.REGISTRY.items()) == before

    failures = (
        ((object(),), ("bad-type",), TypeError),
        (
            (_codec("duplicate"), _codec("duplicate")),
            ("duplicate", "duplicate"),
            ValueError,
        ),
        ((_codec("wrong-id"),), ("expected-id",), ValueError),
        ((_codec("npy"),), ("npy",), ValueError),
    )
    for codecs, expected_ids, error in failures:
        with pytest.raises(error):
            registry._install_builtin_family(codecs, expected_ids)
        assert id(registry.REGISTRY) == registry_id
        assert tuple(registry.REGISTRY.items()) == before


def test_facade_has_one_top_level_builtin_publication():
    source = (ROOT / "src/sceneio/io/registry.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    top_level_calls = []
    top_level_registry_writes = []
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for node in ast.walk(statement):
            if isinstance(node, ast.Call):
                top_level_calls.append(node)
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.ctx, ast.Store)
                and isinstance(node.value, ast.Name)
                and node.value.id == "REGISTRY"
            ):
                top_level_registry_writes.append(node)

    called_names = [
        node.func.id
        for node in top_level_calls
        if isinstance(node.func, ast.Name)
    ]
    assert "register" not in called_names
    assert "_install_builtin_family" not in called_names
    assert called_names.count("_publish_builtin_definitions") == 1
    assert not top_level_registry_writes
    assert not hasattr(registry, "BuiltinAssembly")
    assert not hasattr(registry, "publish_builtin_definitions")

    finalize_calls = [
        node
        for node in top_level_calls
        if isinstance(node.func, ast.Attribute)
        and node.func.attr == "finalize"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "_BUILTIN_ASSEMBLY"
    ]
    assert len(finalize_calls) == 1


def test_fresh_import_observes_empty_then_one_complete_publication():
    code = textwrap.dedent(
        """
        import dis
        import json
        import sys

        report = {
            "finalize_calls": 0,
            "finalize_returns": [],
            "publish_calls": 0,
            "register_calls": 0,
            "installer_calls": 0,
            "update_before": [],
            "update_after": [],
            "update_target_ids": [],
            "registry_sizes": [],
            "extension_bootstrap_returns": [],
            "publication_events": [],
            "subscription_stores": 0,
        }
        opcode_names = {}

        def normalized(filename):
            return filename.replace("\\\\", "/")

        def profile(frame, event, arg):
            filename = normalized(frame.f_code.co_filename)
            name = frame.f_code.co_name
            is_assembly = filename.endswith(
                "/sceneio/io/_registry/assembly.py"
            )
            is_registry = filename.endswith("/sceneio/io/registry.py")
            if event == "call":
                if is_assembly and name == "finalize":
                    report["finalize_calls"] += 1
                elif is_assembly and name == "publish_builtin_definitions":
                    report["publish_calls"] += 1
                elif is_registry and name == "register":
                    report["register_calls"] += 1
                elif is_registry and name == "_install_builtin_family":
                    report["installer_calls"] += 1
            elif event == "return":
                if is_assembly and name == "finalize":
                    report["finalize_returns"].append(
                        [codec.id for codec in arg]
                    )
                    report["publication_events"].append("finalize_return")
                elif is_registry and name == "_registered_image_extensions":
                    report["extension_bootstrap_returns"].append(sorted(arg))
            elif (
                event == "c_call"
                and is_assembly
                and name == "publish_builtin_definitions"
                and getattr(arg, "__name__", "") == "update"
            ):
                target = frame.f_locals["registry"]
                report["update_before"].append(len(target))
                report["update_target_ids"].append(id(target))
                report["publication_events"].append("update_call")
            elif (
                event == "c_return"
                and is_assembly
                and name == "publish_builtin_definitions"
                and getattr(arg, "__name__", "") == "update"
            ):
                report["update_after"].append(len(frame.f_locals["registry"]))
                report["publication_events"].append("update_return")

        def trace(frame, event, arg):
            is_registry = normalized(frame.f_code.co_filename).endswith(
                "/sceneio/io/registry.py"
            )
            if event == "call" and is_registry and frame.f_code.co_name == "<module>":
                frame.f_trace_opcodes = True
            elif event == "line" and is_registry:
                target = frame.f_globals.get("REGISTRY")
                if isinstance(target, dict):
                    report["registry_sizes"].append(len(target))
            elif event == "opcode" and is_registry:
                names = opcode_names.get(frame.f_code)
                if names is None:
                    names = {
                        instruction.offset: instruction.opname
                        for instruction in dis.get_instructions(frame.f_code)
                    }
                    opcode_names[frame.f_code] = names
                if names.get(frame.f_lasti) == "STORE_SUBSCR":
                    report["subscription_stores"] += 1
            return trace

        sys.setprofile(profile)
        sys.settrace(trace)
        from sceneio.io import registry
        sys.settrace(None)
        sys.setprofile(None)

        report["registry_id"] = id(registry.REGISTRY)
        report["registry_ids"] = list(registry.REGISTRY)
        report["definition_ids"] = [
            codec.id for codec in registry.BUILTIN_DEFINITIONS
        ]
        report["all_live_identities"] = all(
            registry.REGISTRY[codec.id] is codec
            for codec in registry.BUILTIN_DEFINITIONS
        )
        report["final_image_extensions"] = sorted(
            registry._IMAGE_FRAME_ACCESS.image_extensions()
        )
        print(json.dumps(report))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)
    canonical = list(CANONICAL_BUILTIN_IDS)

    assert report["finalize_calls"] == 1
    assert report["finalize_returns"] == [canonical]
    assert report["publish_calls"] == 1
    assert report["register_calls"] == 0
    assert report["installer_calls"] == 0
    assert report["update_before"] == [0]
    assert report["update_after"] == [len(canonical)]
    assert report["update_target_ids"] == [report["registry_id"]]
    assert report["publication_events"] == [
        "finalize_return",
        "update_call",
        "update_return",
    ]
    assert report["subscription_stores"] == 0
    assert set(report["registry_sizes"]) == {0, len(canonical)}
    assert report["registry_sizes"][0] == 0
    assert report["registry_sizes"][-1] == len(canonical)
    assert report["extension_bootstrap_returns"] == [[]]
    assert report["registry_ids"] == canonical
    assert report["definition_ids"] == canonical
    assert report["all_live_identities"]
    assert report["final_image_extensions"]


def test_old_and_reloaded_sequence_codecs_share_live_extension_catalog():
    code = textwrap.dedent(
        """
        import importlib
        import tempfile
        from pathlib import Path

        from sceneio import Codec, _core
        from sceneio.io import registry
        from sceneio.io._inspectors.model import Inspection

        old_codec = registry.REGISTRY["image_sequence"]
        old_access = registry._IMAGE_FRAME_ACCESS
        registry = importlib.reload(registry)
        new_codec = registry.REGISTRY["image_sequence"]
        new_access = registry._IMAGE_FRAME_ACCESS

        def inspect_frame(path):
            return Inspection(
                format="assembly_sequence_probe",
                payload_kind="image",
                byte_size=Path(path).stat().st_size,
                shape=(2, 3, 1),
                dtype="uint8",
                channels=1,
            )

        probe = Codec(
            "assembly-sequence-probe",
            (".assemblyprobe",),
            lambda path: path,
            lambda record, path: None,
            record=_core.Image,
            payload_kind="image",
            inspect=inspect_frame,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "frame.assemblyprobe").write_bytes(b"frame")
            (source / "sceneio_sequence.json").write_text(
                '{"sceneio_image_sequence":1,'
                '"frames":[{"file":"frame.assemblyprobe"}]}',
                encoding="utf-8",
            )
            registry.register(probe)
            records = []
            try:
                assert ".assemblyprobe" in old_access.image_extensions()
                assert ".assemblyprobe" in new_access.image_extensions()
                for index, codec in enumerate((old_codec, new_codec)):
                    record = codec.read(str(source))
                    records.append(record)
                    assert codec.inspect(str(source)).shape == (1, 2, 3, 1)
                    assert codec.read_frames(str(source), 0, 1).num_frames == 1
                    destination = root / f"copy-{index}"
                    codec.write(record, str(destination))
                    assert (
                        destination / "frame.assemblyprobe"
                    ).read_bytes() == b"frame"
            finally:
                assert registry.REGISTRY.pop(probe.id) is probe

            assert ".assemblyprobe" not in old_access.image_extensions()
            assert ".assemblyprobe" not in new_access.image_extensions()
            for index, codec in enumerate((old_codec, new_codec)):
                operations = (
                    lambda: codec.read(str(source)),
                    lambda: codec.inspect(str(source)),
                    lambda: codec.read_frames(str(source), 0, 1),
                    lambda: codec.write(
                        records[index],
                        str(root / f"removed-{index}"),
                    ),
                )
                for operation in operations:
                    try:
                        operation()
                    except ValueError as error:
                        assert "unsupported frame extension" in str(error)
                    else:
                        raise AssertionError(
                            "removed frame extension remained available"
                        )
        """
    )
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)


def test_assembly_dependency_direction_and_import_delta_are_exact():
    source = inspect.getsource(assembly)
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported == {
        "__future__",
        "sceneio.contracts.payloads",
        "sceneio.io._builtin_manifest",
        "sceneio.io._registry.model",
    }
    assert "sceneio.io.registry" not in source
    assert "_core" not in source

    code = (
        "import json,sys;"
        "import sceneio;sceneio.codecs();"
        "print(json.dumps(sorted(name for name in sys.modules "
        "if name=='sceneio' or name.startswith('sceneio.'))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    modules = json.loads(result.stdout)
    intentional_additions = {
        "sceneio._camera_models",
        "sceneio._correspondence",
        "sceneio._data",
        "sceneio._data._validation",
        "sceneio._data.calibration",
        "sceneio._data.dense",
        "sceneio._data.features",
        "sceneio._data.pointcloud",
        "sceneio._data.priors",
        "sceneio._data.raster",
        "sceneio._data.transforms",
        "sceneio._data.views",
        "sceneio._posed_views",
        "sceneio.contracts",
        "sceneio.contracts.payloads",
        "sceneio.coordinate_conversion",
        "sceneio.coordinates",
        "sceneio.io._coordinate_manifest",
        "sceneio.io._inspectors.arrays",
        "sceneio.io._inspectors.dense",
        "sceneio.io._inspectors.points",
        "sceneio.io._inspectors.reconstruction",
        "sceneio.io._inspectors.splats",
        "sceneio.io._arrow",
        "sceneio.io._avif",
        "sceneio.io._e57",
        "sceneio.io._euroc_dataset",
        "sceneio.io._euroc_dataset.codec",
        "sceneio.io._euroc_dataset.model",
        "sceneio.io._euroc_dataset.yaml_subset",
        "sceneio.io._hdf5",
        "sceneio.io._label_map",
        "sceneio.io._ncore",
        "sceneio.io._ncore.component_io",
        "sceneio.io._ncore.itar",
        "sceneio.io._ncore.model",
        "sceneio.io._ncore.projection",
        "sceneio.io._ncore.schema",
        "sceneio.io._ncore.writer",
        "sceneio.io._openvdb",
        "sceneio.io._rtmv",
        "sceneio.io._tiff",
        "sceneio.io._usd",
        "sceneio.io._usd.animation",
        "sceneio.io._usd.cameras",
        "sceneio.io._usd.gaussians",
        "sceneio.io._usd.geometry",
        "sceneio.io._usd.instances",
        "sceneio.io._usd.materials",
        "sceneio.io._usd.package",
        "sceneio.io._usd.points",
        "sceneio.io._usd.provider",
        "sceneio.io._usd.semantics",
        "sceneio.io._usd.stage",
        "sceneio.io._usd.volumes",
        "sceneio.io._zarr",
        "sceneio.io._registry.assembly",
        "sceneio.io._registry.coordinates",
        "sceneio.io._registry.families.arrays",
        "sceneio.io._registry.families.containers",
        "sceneio.io._registry.families.datasets",
        "sceneio.io._registry.families.dense",
        "sceneio.io._registry.families.points",
        "sceneio.io._registry.families.reconstruction",
        "sceneio.io._registry.families.splats",
    }
    assert intentional_additions <= set(modules)
    parent_modules = [
        name for name in modules if name not in intentional_additions
    ]
    parent_payload = json.dumps(parent_modules, separators=(",", ":"))
    assert len(parent_modules) == CONTRACT["import_parent"]["module_count"]
    assert hashlib.sha256(parent_payload.encode()).hexdigest() == (
        CONTRACT["import_parent"]["ordered_modules_sha256"]
    )
    assert CONTRACT["import_parent"]["windows_samples"] == 15
    boundaries = CONTRACT["import_parent"]["boundaries"]
    assert tuple(boundaries) == ("import_sceneio", "import_io", "import_core")
    for boundary in boundaries.values():
        assert boundary["candidate_median_ms"] <= (
            boundary["parent_median_ms"]
            + boundary["maximum_median_increase_ms"]
        )
    assert (
        boundaries["import_io"]["candidate_module_count"]
        - boundaries["import_io"]["parent_module_count"]
        == 1
    )
    for name in ("import_sceneio", "import_core"):
        assert boundaries[name]["candidate_module_count"] == (
            boundaries[name]["parent_module_count"]
        )

    candidate = CONTRACT["pytest_candidate_collection"]
    ignored_collection_paths = candidate.get("collection_ignored_paths", [])
    collection = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            *(f"--ignore={path}" for path in ignored_collection_paths),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    node_ids = []
    for line in collection.stdout.splitlines():
        if "::" not in line or line.startswith("="):
            continue
        node_id = line.strip().replace("\\", "/")
        while "//" in node_id:
            node_id = node_id.replace("//", "/")
        node_ids.append(node_id)
    feature_added_nodes = set(candidate["added_nodes"])
    feature_removed_nodes = set(candidate["removed_nodes"])
    actual_nodes = set(node_ids)
    assert feature_added_nodes <= actual_nodes
    assert feature_removed_nodes.isdisjoint(actual_nodes)
    rename_groups = candidate["renamed_node_groups"]
    expected_groups = {
        "streaming": (
            "tests/test_io_mmap.py::",
            "tests/test_io_streaming.py::",
            15,
        ),
        "inspection": (
            "tests/test_io_mmap.py::",
            "tests/test_io_inspection.py::",
            76,
        ),
        "partial_arrays": (
            "tests/test_io_partial.py::",
            "tests/test_io_partial_arrays.py::",
            3,
        ),
        "partial_images": (
            "tests/test_io_partial.py::",
            "tests/test_io_partial_images.py::",
            10,
        ),
        "partial_meshes": (
            "tests/test_io_partial.py::",
            "tests/test_io_partial_meshes.py::",
            1,
        ),
        "partial_points": (
            "tests/test_io_partial.py::",
            "tests/test_io_partial_points.py::",
            13,
        ),
        "partial_reconstruction": (
            "tests/test_io_partial.py::",
            "tests/test_io_partial_reconstruction.py::",
            15,
        ),
    }
    assert [item["name"] for item in rename_groups] == list(expected_groups)
    renamed_from = set()
    renamed_to = set()
    for group in rename_groups:
        expected_from, expected_to, expected_count = expected_groups[group["name"]]
        assert group["from_prefix"] == expected_from
        assert group["to_prefix"] == expected_to
        module_path = group["to_prefix"].removesuffix("::")
        module_tree = ast.parse((ROOT / module_path).read_text(encoding="utf-8"))
        excluded_functions = set(group["excluded_function_names"])
        function_nodes = [
            node
            for node in module_tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name not in excluded_functions
        ]
        assert len(function_nodes) == group["function_count"]
        function_payload = "\n".join(
            ast.dump(node, include_attributes=False) for node in function_nodes
        )
        assert hashlib.sha256(function_payload.encode()).hexdigest() == (
            group["function_ast_sha256"]
        )
        suffixes = group["node_suffixes"]
        assert len(suffixes) == expected_count
        assert len(set(suffixes)) == expected_count
        for suffix in suffixes:
            renamed_from.add(group["from_prefix"] + suffix)
            renamed_to.add(group["to_prefix"] + suffix)
    expected_rename_count = sum(group[2] for group in expected_groups.values())
    assert len(renamed_from) == expected_rename_count
    assert len(renamed_to) == expected_rename_count
    assert renamed_from.isdisjoint(actual_nodes)
    assert renamed_to <= actual_nodes
    assert feature_added_nodes.isdisjoint(feature_removed_nodes)
    assert feature_added_nodes.isdisjoint(renamed_to)
    assert feature_removed_nodes.isdisjoint(renamed_from)
    support_groups = candidate["moved_support_groups"]
    expected_support_groups = {
        "partial_image_window": (
            "tests/test_io_partial.py",
            "tests/_support/partial_read.py",
            ["_pixels", "_assert_image_window"],
        ),
        "partial_point_range": (
            "tests/test_io_partial.py",
            "tests/_support/partial_read.py",
            ["_assert_point_range"],
        ),
        "partial_process_rss": (
            "tests/test_io_partial.py",
            "tests/_support/partial_read.py",
            ["_fresh_process_partial_rss"],
        ),
        "partial_reconstruction_helpers": (
            "tests/test_io_partial.py",
            "tests/test_io_partial_reconstruction.py",
            [
                "_three_view_reconstruction",
                "_fresh_process_colmap_error_rss",
                "_assert_payload_relative_rss",
                "_assert_colmap_error_rss_is_sublinear",
                "_traced_format_error_peak",
                "_write_malformed_observation_model",
                "_write_unterminated_name_model",
                "_instrumented_rss_measurement",
                "_write_malformed_text_token_model",
            ],
        ),
    }
    assert [item["name"] for item in support_groups] == list(
        expected_support_groups
    )
    for group in support_groups:
        expected_from, expected_to, expected_functions = (
            expected_support_groups[group["name"]]
        )
        assert group["from_path"] == expected_from
        assert group["to_path"] == expected_to
        source_tree = ast.parse(
            (ROOT / group["from_path"]).read_text(encoding="utf-8")
        )
        destination_tree = ast.parse(
            (ROOT / group["to_path"]).read_text(encoding="utf-8")
        )
        function_names = group["function_names"]
        assert function_names == expected_functions
        assert not {
            node.name
            for node in source_tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        } & set(function_names)
        function_nodes = [
            node
            for node in destination_tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in function_names
        ]
        assert [node.name for node in function_nodes] == function_names
        function_payload = "\n".join(
            ast.dump(node, include_attributes=False) for node in function_nodes
        )
        assert hashlib.sha256(function_payload.encode()).hexdigest() == (
            group["function_ast_sha256"]
        )
    partial_disposition = candidate["partial_family_disposition"]
    assert {
        family: details["status"]
        for family, details in partial_disposition.items()
        if family != "retained_cross_family"
    } == {
        "sequence": "already_family_owned",
        "splats": "already_family_owned_with_cross_family_invariants_retained",
    }
    for family in ("sequence", "splats"):
        for anchor in partial_disposition[family]["anchors"]:
            anchor_tree = ast.parse(
                (ROOT / anchor["path"]).read_text(encoding="utf-8")
            )
            anchor_functions = {
                node.name: node
                for node in anchor_tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            function_nodes = [
                anchor_functions[name] for name in anchor["function_names"]
            ]
            function_payload = "\n".join(
                ast.dump(node, include_attributes=False)
                for node in function_nodes
            )
            assert hashlib.sha256(function_payload.encode()).hexdigest() == (
                anchor["function_ast_sha256"]
            )
            anchor_prefix = anchor["path"] + "::"
            anchor_function_names = set(anchor["function_names"])
            collected_anchor_nodes = {
                node_id
                for node_id in actual_nodes
                if node_id.startswith(anchor_prefix)
                and node_id.rsplit("::", maxsplit=1)[-1].split("[", maxsplit=1)[
                    0
                ]
                in anchor_function_names
            }
            assert len(anchor["node_ids"]) == len(set(anchor["node_ids"]))
            assert collected_anchor_nodes == set(anchor["node_ids"])
    retained = partial_disposition["retained_cross_family"]
    retained_path = ROOT / retained["path"]
    retained_tree = ast.parse(retained_path.read_text(encoding="utf-8"))
    retained_functions = {
        node.name: node
        for node in retained_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    retained_nodes = [
        retained_functions[name] for name in retained["function_names"]
    ]
    retained_payload = "\n".join(
        ast.dump(node, include_attributes=False) for node in retained_nodes
    )
    assert hashlib.sha256(retained_payload.encode()).hexdigest() == (
        retained["function_ast_sha256"]
    )
    function_format_ids = retained["function_format_ids"]
    assert list(function_format_ids) == retained["function_names"]
    observed_shared_ids = set()
    for function_name, function_node in zip(
        retained["function_names"],
        retained_nodes,
        strict=True,
    ):
        observed_format_ids = sorted(
            {
                node.value
                for node in ast.walk(function_node)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in CANONICAL_BUILTIN_IDS
            }
        )
        assert observed_format_ids == function_format_ids[function_name]
        observed_shared_ids.update(observed_format_ids)
    assert observed_shared_ids.isdisjoint(FAMILY_MEMBERS["sequences"])
    assert observed_shared_ids & set(FAMILY_MEMBERS["splats"]) == {
        "gaussian_ply",
        "compressed_ply",
        "sog",
        "ksplat",
        "splat",
    }
    assert observed_shared_ids - set(FAMILY_MEMBERS["splats"])

    ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "bench/compare_io_structure.py" in ci_workflow
    ci_lines = ci_workflow.splitlines()
    windows_mmap_command = next(
        line
        for line in ci_lines
        if "run: .venv/Scripts/python.exe -m pytest" in line
        and "tests/test_io_mmap.py" in line
    )
    non_windows_mmap_command = next(
        line
        for line in ci_lines
        if "run: .venv/bin/python -m pytest" in line
        and "tests/test_io_mmap.py" in line
    )
    assert windows_mmap_command.count("tests/test_io_streaming.py") == 1
    assert non_windows_mmap_command.count("tests/test_io_streaming.py") == 1
    assert windows_mmap_command.count("tests/test_io_inspection.py") == 1
    assert non_windows_mmap_command.count("tests/test_io_inspection.py") == 1
    assert windows_mmap_command.count("tests/test_io_partial_arrays.py") == 1
    assert non_windows_mmap_command.count("tests/test_io_partial_arrays.py") == 1
    assert windows_mmap_command.count("tests/test_io_partial_images.py") == 1
    assert non_windows_mmap_command.count("tests/test_io_partial_images.py") == 1
    assert windows_mmap_command.count("tests/test_io_partial_meshes.py") == 1
    assert non_windows_mmap_command.count("tests/test_io_partial_meshes.py") == 1
    assert windows_mmap_command.count("tests/test_io_partial_points.py") == 1
    assert non_windows_mmap_command.count("tests/test_io_partial_points.py") == 1
    assert (
        windows_mmap_command.count(
            "tests/test_io_partial_reconstruction.py"
        )
        == 1
    )
    assert (
        non_windows_mmap_command.count(
            "tests/test_io_partial_reconstruction.py"
        )
        == 1
    )
    assert (
        "bench/bench_io.py --runs 1 --scale 0.001 --skip-oracles --json"
        in ci_workflow
    )
    strict_guard_command = (
        'run: .venv/bin/python bench/bench_io.py --runs 5 '
        '--strict-oracles --require-o4-gains '
        '--require-o5-inspect-gains --require-o5-partial-gains '
        '--json "${{ runner.temp }}/sceneio-benchmark-guard.json"'
    )
    assert ci_workflow.count(strict_guard_command) == 1
    assert "run: .venv/bin/python -m ruff check" in ci_workflow
    assert "reconstruction-platform:" in ci_workflow
    reconstruction_job = ci_workflow.split(
        "  reconstruction-platform:",
        maxsplit=1,
    )[1].split("  manylinux2014-portability:", maxsplit=1)[0]
    assert (
        ci_workflow.count("tests/test_io_reconstruction_family_architecture.py")
        == 3
    )
    manylinux_job = ci_workflow.split(
        "  manylinux2014-portability:",
        maxsplit=1,
    )[1]
    splat_job = ci_workflow.split(
        "  splat-platform:",
        maxsplit=1,
    )[1].split("  manylinux2014-portability:", maxsplit=1)[0]
    assert (
        'uv pip install -e ".[dev]" "numpy>=2.0,<2.5" '
        '"gsply==0.4.6" "pillow>=10.0"'
    ) in splat_job
    assert "actions/setup-node@v4" in splat_job
    assert (
        "cache-dependency-path: tools/splat-transform-oracle/package-lock.json"
        in splat_job
    )
    assert splat_job.count("Install locked SplatTransform oracle") == 2
    assert splat_job.count("npm ci --prefix") == 2
    assert "@playcanvas/splat-transform@3.1.6" not in splat_job
    assert splat_job.count("SCENEIO_SPLAT_TRANSFORM_CLI=") == 2
    assert splat_job.count("tests/test_io_splat_family_architecture.py") == 2
    assert splat_job.count("-m pytest -q -rs") == 2
    for suite in (
        "test_ply.py",
        "test_compressed_ply.py",
        "test_sog.py",
        "test_ksplat.py",
        "test_spz.py",
        "test_splat.py",
        "test_splat_transform_oracle.py",
    ):
        assert splat_job.count(f"tests/codecs/{suite}") == 2
    assert (
        "SCENEIO_SPLAT_PARENT_PROFILE: ${{ matrix.parent-profile }}"
        in splat_job
    )
    for runner, profile in (
        ("ubuntu-latest", "ubuntu_latest_x86_64_glibc"),
        ("windows-latest", "windows_msvc_x86_64"),
        ("macos-latest", "macos_appleclang_arm64"),
    ):
        assert (
            f"          - os: {runner}\n"
            f"            parent-profile: {profile}"
        ) in splat_job
    assert (
        "SCENEIO_SPLAT_PARENT_PROFILE=manylinux2014_gcc10_x86_64"
        in manylinux_job
    )
    assert 'PYTHONPATH=/work "$py" -m pytest -q \\' in manylinux_job
    for test_name in (
        "test_colmap_binary_checks_selected_observation_bytes_before_allocating",
        "test_colmap_binary_validates_selected_name_terminator_before_allocating",
        "test_colmap_observation_error_rss_growth_is_payload_relative",
        "test_colmap_name_error_rss_growth_is_payload_relative",
    ):
        expected_path = (
            "/work/tests/test_io_partial_reconstruction.py::" + test_name
        )
        stale_path = "/work/tests/test_io_partial.py::" + test_name
        assert manylinux_job.count(expected_path) == 1
        assert stale_path not in manylinux_job
    for suite in (
        "test_colmap.py",
        "test_transforms_json.py",
        "test_pose_text.py",
        "test_euroc_state.py",
        "test_g2o.py",
        "test_colmap_db.py",
        "test_colmap_txt.py",
        "test_bundler.py",
        "test_bal.py",
        "test_nvm.py",
        "test_openmvg.py",
    ):
        assert reconstruction_job.count(f"tests/codecs/{suite}") == 2

    benchmark_contract = CONTRACT["benchmark_parent"]
    assert benchmark_contract["captures"] == [
        "build/c3-c4-local-benchmark-952bb8d.json",
        "build/ci-30762546918-benchmark/sceneio-benchmark.json",
    ]
    assert benchmark_contract["source_commit"] == (
        "41ff8cac2ecb3d58b5f7ea46dc89d8c4bac2b69d"
    )
    assert benchmark_contract["hosted_run"] == 30762546918
    assert benchmark_contract["extension_capture"] == (
        "build/apng-56-row-benchmark.json"
    )
    assert benchmark_contract["extension_base_commit"] == (
        "3c07bcefabbd0d9be935ffd22c5ef1e7f4642321"
    )
    assert benchmark_contract["rows"] == 74
    assert len(CANONICAL_BUILTIN_IDS) == benchmark_contract["rows"]
    assert benchmark_contract["structural_projection_sha256"] == (
        "3f392b8d9f248457a2a8f0d8d40b56d6e7a962a2012d113e4fae94d6de4d6a2d"
    )
    assert benchmark_contract["representation_reset"] == {
        "release": "0.4.0",
        "date": "2026-08-30",
        "baseline_commit": "182c9120",
        "baseline_structural_projection_sha256": (
            "5b68b2f03f8de343dd681a531cc7f1a293dcfe94c565e164cfc725f0c109ad01"
        ),
        "changes": [
            "Reconstruction payload accounting includes the aggregate-owned "
            "camera_ids array.",
            "Unified SceneGraph USD output emits the standard mesh extent property.",
        ],
    }
    rows = [
        {
            "codec": "probe",
            "payload_mb": 1.25,
            "read_peak_mb": 0.125,
            "read_mbps": 100.0,
            "read_rss_mb": 2.0,
            "partial_peak_mb": None,
            "nested": {
                "inspect_peak_mb": 0.25,
                "file_mb": 0.75,
            },
        }
    ]
    projected = compare_io_structure.structural_projection(
        rows, benchmark_contract
    )
    assert projected == [
        {
            "codec": "probe",
            "payload_mb": 1.25,
            "read_peak_mb": "<runtime-dependent>",
            "partial_peak_mb": None,
            "nested": {
                "inspect_peak_mb": "<runtime-dependent>",
                "file_mb": 0.75,
            },
        }
    ]
    synthetic_contract = {
        "benchmark_parent": {
            **benchmark_contract,
            "rows": 1,
            "structural_projection_sha256": (
                "1af7aad7247bb81755ab377b81dccdc964287e77ab46bbcb81d39b1442700caf"
            ),
        }
    }
    compare_io_structure.validate(rows, synthetic_contract)

    peak_changed = copy.deepcopy(rows)
    peak_changed[0]["read_peak_mb"] = 999.0
    peak_changed[0]["nested"]["inspect_peak_mb"] = 777.0
    assert compare_io_structure.structural_projection(
        peak_changed, benchmark_contract
    ) == projected
    compare_io_structure.validate(peak_changed, synthetic_contract)

    peak_missing = copy.deepcopy(rows)
    del peak_missing[0]["nested"]["inspect_peak_mb"]
    assert compare_io_structure.structural_projection(
        peak_missing, benchmark_contract
    ) != projected
    with pytest.raises(ValueError, match="benchmark structure hash"):
        compare_io_structure.validate(peak_missing, synthetic_contract)

    peak_renamed = copy.deepcopy(rows)
    peak_renamed[0]["renamed_peak_mb"] = peak_renamed[0].pop(
        "read_peak_mb"
    )
    with pytest.raises(ValueError, match="benchmark structure hash"):
        compare_io_structure.validate(peak_renamed, synthetic_contract)

    invalid_peak = copy.deepcopy(rows)
    invalid_peak[0]["read_peak_mb"] = {"unexpected": ["shape"]}
    with pytest.raises(
        TypeError,
        match=r"probe\.read_peak_mb must be a numeric scalar or null",
    ):
        compare_io_structure.structural_projection(
            invalid_peak, benchmark_contract
        )

    stable_changed = copy.deepcopy(rows)
    stable_changed[0]["nested"]["file_mb"] = 0.5
    assert compare_io_structure.structural_projection(
        stable_changed, benchmark_contract
    ) != projected
    with pytest.raises(ValueError, match="benchmark structure hash"):
        compare_io_structure.validate(stable_changed, synthetic_contract)
