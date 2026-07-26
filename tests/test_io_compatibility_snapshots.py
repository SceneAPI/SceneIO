"""Checked compatibility snapshots for the behavior-preserving R1 boundary."""

from __future__ import annotations

import ast
import dataclasses
import json
import pickle
import re
import statistics
import subprocess
import sys
import textwrap
from collections import defaultdict
from pathlib import Path

import pytest

import sceneio
import sceneio.io
from sceneio import _core
from sceneio.io import registry
from sceneio.io._builtin_manifest import CANONICAL_BUILTIN_IDS
from sceneio.io._depth import DepthEncoding
from sceneio.io._inspection import ArrayInspection, Inspection

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "tests" / "contracts"

_SELECTORS = (
    ("window", "read_window"),
    ("points", "read_points"),
    ("faces", "read_faces"),
    ("mesh_id", "read_mesh"),
    ("primitive_id", "read_primitive"),
    ("states", "read_states"),
    ("frames", "read_frames"),
    ("image_id", "read_image"),
    ("pair", "read_pair"),
    ("tensors", "read_tensors"),
    ("slices", "read_slices"),
)


def _read_json(name: str):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _jsonable(value):
    return json.loads(json.dumps(value))


def _registry_snapshot():
    codecs = []
    extensions: dict[str, list[str]] = defaultdict(list)
    filenames: dict[str, list[str]] = defaultdict(list)
    directory_markers: dict[str, list[str]] = defaultdict(list)
    magic_entries: list[tuple[str, str]] = []
    for codec in registry.BUILTIN_DEFINITIONS:
        record = None
        if codec.record is not None:
            record = {
                "module": codec.record.__module__,
                "qualname": codec.record.__qualname__,
            }
        codecs.append(
            {
                "id": codec.id,
                "extensions": list(codec.extensions),
                "magic_hex": [value.hex() for value in codec.magic],
                "filenames": list(codec.filenames),
                "is_directory": codec.is_directory,
                "dir_marker": codec.dir_marker,
                "container_kind": codec.container_kind,
                "datatype": codec.datatype,
                "record": record,
                "selectors": [
                    name for name, field in _SELECTORS if getattr(codec, field) is not None
                ],
                "streams_read": codec.streams_read,
                "streams_write": codec.streams_write,
                "lossy": codec.lossy,
                "requires_features": list(codec.requires_features),
                "supported_features": list(codec.supported_features),
                "unsupported_features": list(codec.unsupported_features),
                "capabilities": _jsonable(
                    dataclasses.asdict(codec.capabilities())
                ),
            }
        )
        for extension in codec.extensions:
            extensions[extension].append(codec.id)
        for filename in codec.filenames:
            filenames[filename].append(codec.id)
        if codec.is_directory:
            directory_markers[codec.dir_marker].append(codec.id)
        magic_entries.extend((value.hex(), codec.id) for value in codec.magic)

    prefix_collisions = []
    for index, (left, left_id) in enumerate(magic_entries):
        left_bytes = bytes.fromhex(left)
        for right, right_id in magic_entries[index + 1 :]:
            right_bytes = bytes.fromhex(right)
            if left_bytes.startswith(right_bytes) or right_bytes.startswith(left_bytes):
                prefix_collisions.append([left, left_id, right, right_id])

    def collisions(values):
        return {
            key: members
            for key, members in sorted(values.items())
            if len(members) > 1
        }

    return {
        "schema_version": 1,
        "codecs": codecs,
        "collisions": {
            "extensions": collisions(extensions),
            "filenames": collisions(filenames),
            "directory_markers": collisions(directory_markers),
            "magic_prefixes": prefix_collisions,
        },
    }


def _type_contract(value_type: type):
    return {
        "module": value_type.__module__,
        "qualname": value_type.__qualname__,
    }


def _pickle_outcome(value):
    try:
        restored = pickle.loads(pickle.dumps(value))
    except Exception as exc:
        return {
            "outcome": "raises",
            "exception": type(exc).__name__,
            "message_prefix": str(exc).split(" at ")[0],
        }
    return {
        "outcome": "roundtrip",
        "type_identity": type(restored) is type(value),
        "equal": restored == value,
    }


def _exception_outcome(operation, expected_prefix: str):
    try:
        operation()
    except Exception as exc:
        if not str(exc).startswith(expected_prefix):
            raise AssertionError(
                f"{type(exc).__name__} message does not start with "
                f"{expected_prefix!r}: {exc}"
            ) from exc
        return {
            "module": type(exc).__module__,
            "qualname": type(exc).__qualname__,
            "message_prefix": expected_prefix,
        }
    raise AssertionError("operation did not raise")


def _public_snapshot():
    record_names = (
        "Camera",
        "CameraRig",
        "ColmapDatabase",
        "DepthMap",
        "FeatureSet",
        "FlowField",
        "GaussianCloud",
        "Image",
        "ImageSequence",
        "MatchGraph",
        "MaterialSet",
        "Mesh",
        "MeshScene",
        "PointCloud",
        "PoseGraph",
        "PosedViewSet",
        "Reconstruction",
        "StateTrajectory",
        "TensorDict",
    )
    examples = {
        "Codec": registry.REGISTRY["npy"],
        "CodecCapabilities": sceneio.capabilities("npy"),
        "NativeFeatureCapabilities": sceneio.native_features("hdf5"),
        "DepthEncoding": DepthEncoding(
            unit="meters",
            scale_to_meters=1.0,
            invalid_policy="none",
        ),
        "ArrayInspection": ArrayInspection("values", (2, 3), "float32"),
        "Inspection": Inspection(
            format="npy",
            datatype="tensor",
            byte_size=128,
            shape=(2, 3),
            dtype="float32",
            count=6,
        ),
    }
    types = {
        name: {
            **_type_contract(type(value)),
            "repr_normalized": re.sub(r"0x[0-9a-fA-F]+", "0xADDRESS", repr(value)),
            "pickle": _pickle_outcome(value),
        }
        for name, value in examples.items()
    }
    reexports = {}
    for name in sorted(sceneio._IO_FORWARDS):
        reexports[name] = getattr(sceneio, name) is getattr(sceneio.io, name)
    return {
        "schema_version": 1,
        "sceneio_all": sceneio.__all__,
        "sceneio_io_all": sceneio.io.__all__,
        "namespaces": sorted(sceneio._NAMESPACES),
        "io_forwards": sorted(sceneio._IO_FORWARDS),
        "reexport_identity": reexports,
        "types": types,
        "format_error": _type_contract(sceneio.FormatError),
        "source_identity": {
            "Codec": sceneio.io.Codec is registry.Codec,
            "CodecCapabilities": (
                sceneio.io.CodecCapabilities is registry.CodecCapabilities
            ),
            "NativeFeatureCapabilities": (
                sceneio.io.NativeFeatureCapabilities
                is registry.NativeFeatureCapabilities
            ),
            "ArrayInspection": sceneio.io.ArrayInspection is ArrayInspection,
            "Inspection": sceneio.io.Inspection is Inspection,
            "DepthEncoding": sceneio.io.DepthEncoding is DepthEncoding,
            "FormatError": sceneio.io.FormatError is registry.FormatError,
        },
        "core_record_identity": {
            name: getattr(sceneio.io, name) is getattr(_core, name)
            for name in record_names
        },
        "exceptions": {
            "unknown_codec": _exception_outcome(
                lambda: registry.get("__contract_probe__"),
                "unknown format id ",
            ),
            "unknown_native_feature": _exception_outcome(
                lambda: registry.native_feature_capabilities(
                    "__contract_probe__"
                ),
                "unknown native feature ",
            ),
            "duplicate_registration": _exception_outcome(
                lambda: registry.register(registry.REGISTRY["npy"]),
                "codec id already registered: ",
            ),
        },
        "native_features": {
            name: _jsonable(dataclasses.asdict(feature))
            for name, feature in sceneio.native_features().items()
        },
    }


def test_registry_contract_matches_checked_snapshot():
    assert _registry_snapshot() == _read_json("io_registry_v1.json")


def test_public_contract_matches_checked_snapshot():
    assert _public_snapshot() == _read_json("io_public_v1.json")


def test_compiled_symbol_contract_matches_checked_snapshot():
    expected = (CONTRACTS / "core_symbols_v1.txt").read_text(encoding="utf-8").splitlines()
    actual = sorted(name for name in dir(_core) if not name.startswith("__"))
    assert actual == expected


@pytest.mark.parametrize(
    ("boundary", "statement"),
    [
        ("import_sceneio", "import sceneio"),
        ("import_io", "import sceneio; sceneio.codecs()"),
        ("import_core", "from sceneio import _core"),
    ],
)
def test_import_boundary_matches_checked_module_set(boundary, statement):
    contract = _read_json("io_import_v1.json")
    optional_roots = contract["forbidden_optional_roots"]
    code = (
        "import json,sys,time;"
        "start=time.perf_counter();"
        f"{statement};"
        "duration=(time.perf_counter()-start)*1000;"
        "print(json.dumps({'duration_ms':duration,'modules':sorted("
        "name for name in sys.modules if name=='sceneio' or "
        "name.startswith('sceneio.')),'optional_modules':sorted("
        f"name for name in {optional_roots!r} if name in sys.modules)}}))"
    )
    results = [
        json.loads(
            subprocess.run(
                [sys.executable, "-c", code],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        for _ in range(3)
    ]
    assert all(
        result["modules"] == contract["sceneio_modules"][boundary]
        for result in results
    )
    assert all(not result["optional_modules"] for result in results)
    if sys.platform == "win32":
        assert (
            statistics.median(result["duration_ms"] for result in results)
            < contract["windows_reference"][boundary]["alert_ms"]
        )


def test_benchmark_contract_matches_checked_snapshot():
    contract = _read_json("bench_io_v1.json")
    benchmark_path = ROOT / "bench" / "bench_io.py"
    probe = textwrap.dedent(
        f"""
        import argparse
        import importlib.util
        import json
        import pathlib
        import sys

        original_parse_args = argparse.ArgumentParser.parse_args
        captured = {{}}

        def capturing_parse_args(parser, *unused_args, **unused_kwargs):
            captured["parser"] = parser
            return original_parse_args(parser, [])

        spec = importlib.util.spec_from_file_location(
            "sceneio_bench_contract", {str(benchmark_path)!r}
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module.argparse.ArgumentParser.parse_args = capturing_parse_args
        module._run_benchmark = lambda args, tmp: ([], [])
        module.main()
        parser = captured["parser"]
        actions = [action for action in parser._actions if action.dest != "help"]
        order = [item.id for item in module._specs(0.001)]
        order.extend(("gltf", "colmap_db"))
        order.extend(
            item.id
            for item in module._directory_specs(
                reconstruction=None,
                scale=0.001,
                root=pathlib.Path("build"),
            )
        )
        print(json.dumps({{
            "options": sorted(
                option
                for action in parser._actions
                for option in action.option_strings
                if option.startswith("--")
            ),
            "defaults": {{action.dest: action.default for action in actions}},
            "order": order,
        }}))
        """
    )
    observed = json.loads(
        subprocess.run(
            [sys.executable, "-c", probe],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    assert observed["options"] == contract["cli_options"]
    assert observed["defaults"] == contract["defaults"]
    assert observed["order"] == contract["result_order"]
    assert contract["existing_json_envelope"] == "bare_list"
    assert contract["incompatibilities"] == [
        ["only", "require_o4_gains"],
        ["only", "require_o5_inspect_gains"],
        ["only", "require_o5_partial_gains"],
        ["only", "large_safetensors_mib"],
    ]
    assert set(contract["result_order"]) == set(CANONICAL_BUILTIN_IDS)

    tree = ast.parse(benchmark_path.read_text(encoding="utf-8"))
    literal_dict_keys = {
        frozenset(
            key.value
            for key in node.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
    }
    for keys in contract["row_key_variants"].values():
        assert frozenset(keys) in literal_dict_keys
    assert set(contract["nullable_common_nested_fields"]) <= set(
        contract["row_key_variants"]["common"]
    )

    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    def assigned_dict_keys(function_name: str, variable_name: str):
        candidates = []
        for node in ast.walk(functions[function_name]):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Dict)
                and any(
                    isinstance(target, ast.Name)
                    and target.id == variable_name
                    for target in node.targets
                )
            ):
                candidates.append(
                    sorted(
                        key.value
                        for key in node.value.keys
                        if isinstance(key, ast.Constant)
                        and isinstance(key.value, str)
                    )
                )
        return max(candidates, key=len)

    assert assigned_dict_keys(
        "_run_large_safetensors", "oracle_metrics"
    ) == contract["optional_large_safetensors_keys"]
    assert assigned_dict_keys(
        "_benchmark_colmap_db", "oracle_metrics"
    ) == contract["optional_colmap_db_keys"]


def test_benchmark_json_envelope_common_rows_and_nested_shapes(tmp_path):
    contract = _read_json("bench_io_v1.json")
    output = tmp_path / "benchmark.json"
    selected = ["npy", *contract["nested_shapes"]]
    only_arguments = [
        argument
        for codec_id in selected
        for argument in ("--only", codec_id)
    ]
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "bench" / "bench_io.py"),
            "--runs",
            "1",
            "--scale",
            "0.001",
            "--skip-oracles",
            *only_arguments,
            "--json",
            str(output),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    rows = json.loads(output.read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    assert {row["codec"] for row in rows} == set(selected)
    by_codec = {row["codec"]: row for row in rows}
    for row in rows:
        assert sorted(row) == contract["row_key_variants"]["common"]
        for key, value in row.items():
            if key == "codec":
                assert isinstance(value, str)
            elif key in contract["nullable_common_nested_fields"]:
                assert value is None or isinstance(value, dict)
            else:
                assert value is None or (
                    isinstance(value, int | float)
                    and not isinstance(value, bool)
                )
    for codec_id, codec_shapes in contract["nested_shapes"].items():
        row = by_codec[codec_id]
        for field, shape in codec_shapes.items():
            nested = row[field]
            assert isinstance(nested, dict)
            assert sorted(nested) == shape["keys"]
            if "value_keys" in shape:
                assert all(
                    sorted(value) == shape["value_keys"]
                    for value in nested.values()
                )


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (("--scale", "0"), "--scale must be positive"),
        (("--large-safetensors-mib", "-1"), "--large-safetensors-mib must be non-negative"),
        (
            ("--only", "npy", "--require-o4-gains"),
            "--only cannot be combined with complete-sweep regression guards",
        ),
        (
            ("--only", "npy", "--require-o5-inspect-gains"),
            "--only cannot be combined with complete-sweep regression guards",
        ),
        (
            ("--only", "npy", "--require-o5-partial-gains"),
            "--only cannot be combined with complete-sweep regression guards",
        ),
        (
            ("--only", "npy", "--large-safetensors-mib", "1"),
            "--only cannot be combined with --large-safetensors-mib",
        ),
    ],
)
def test_benchmark_cli_rejection_contract(arguments, message):
    completed = subprocess.run(
        [sys.executable, str(ROOT / "bench" / "bench_io.py"), *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert message in completed.stderr
