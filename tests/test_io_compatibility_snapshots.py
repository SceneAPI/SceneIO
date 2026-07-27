"""Checked compatibility snapshots for the behavior-preserving R1 boundary."""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import hashlib
import importlib.util
import io
import json
import pickle
import re
import statistics
import subprocess
import sys
import tempfile
import textwrap
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
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


def _load_benchmark_module(name: str):
    benchmark_path = ROOT / "bench" / "bench_io.py"
    spec = importlib.util.spec_from_file_location(name, benchmark_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fixture_fingerprint(value) -> str:
    digest = hashlib.sha256()

    def token(data: str | bytes) -> None:
        encoded = data.encode("utf-8") if isinstance(data, str) else data
        digest.update(len(encoded).to_bytes(8, "little"))
        digest.update(encoded)

    def visit(item) -> None:
        if isinstance(item, np.ndarray):
            canonical_dtype = item.dtype.newbyteorder("<")
            canonical = np.ascontiguousarray(
                item.astype(canonical_dtype, copy=False)
            )
            digest.update(b"A")
            token(canonical_dtype.str)
            token(json.dumps(list(item.shape), separators=(",", ":")))
            token(canonical.tobytes(order="C"))
        elif isinstance(item, dict):
            digest.update(b"M")
            for key in sorted(item):
                token(str(key))
                visit(item[key])
        elif isinstance(item, list | tuple):
            digest.update(b"L")
            token(str(len(item)))
            for child in item:
                visit(child)
        elif isinstance(item, np.generic):
            visit(item.item())
        elif item is None or isinstance(item, bool | int | float | str):
            digest.update(b"J")
            token(
                json.dumps(
                    item,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            )
        else:
            raise TypeError(f"unsupported fixture fingerprint value: {type(item)!r}")

    visit(value)
    return digest.hexdigest()


def _record_projection(record, fields):
    return {field: getattr(record, field) for field in fields}


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


def _normalize_pickle_message(message: str) -> str:
    message = message.split(" at ")[0]
    return re.sub(
        r"^Can't (?:get|pickle) local object ",
        "Can't pickle local object ",
        message,
    )


def _pickle_outcome(value):
    try:
        restored = pickle.loads(pickle.dumps(value))
    except Exception as exc:
        return {
            "outcome": "raises",
            "exception": type(exc).__name__,
            "message_prefix": _normalize_pickle_message(str(exc)),
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
    assert {
        _normalize_pickle_message(message)
        for message in (
            "Can't get local object '_mmap_view_reader.<locals>.read'",
            "Can't pickle local object '_mmap_view_reader.<locals>.read'",
        )
    } == {"Can't pickle local object '_mmap_view_reader.<locals>.read'"}
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
    equivalence = contract["r3_1a_equivalence"]
    assert equivalence["parent_commit"] == (
        "683ae483a3a2407dc192fb32cdcf964eb3b1fe9a"
    )
    assert equivalence["parent_tree"] == (
        "5dfe9bbd36940bfa4b03a322a2b452b38d3f463e"
    )
    assert equivalence["parent_benchmark_blob"] == (
        "bcb502936cc8ccce4a52b843a1220f27cdddba1f"
    )
    assert equivalence["candidate_benchmark_blob"] == (
        "9714e081322b925eddc560f1a724b4dd2a68dc78"
    )
    assert equivalence["structural_projection_sha256"] == _read_json(
        "io_registry_assembly_v1.json"
    )["benchmark_parent"]["structural_projection_sha256"]
    assert equivalence["deterministic_projection"] == "identical"
    assert len(equivalence["candidate_capture_sha256"]) == 2
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", value)
        for value in (
            equivalence["parent_capture_sha256"],
            *equivalence["candidate_capture_sha256"],
            equivalence["confirming_strict_capture_sha256"],
        )
    )
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
    _assert_benchmark_components_and_metric_semantics_are_explicit()
    _assert_benchmark_representative_fixtures_match_checked_fingerprints()


def _assert_benchmark_components_and_metric_semantics_are_explicit():
    contract = _read_json("bench_io_v1.json")
    root_count = sys.path.count(str(ROOT))
    benchmark = _load_benchmark_module("sceneio_bench_components")
    assert sys.path.count(str(ROOT)) == root_count
    benchmark_tree = ast.parse(
        (ROOT / "bench" / "bench_io.py").read_text(encoding="utf-8")
    )

    assert benchmark.Spec.__module__ == "bench.io_bench.model"
    assert benchmark.DirectorySpec.__module__ == "bench.io_bench.model"
    assert benchmark._measure.__module__ == "bench.io_bench.measure"
    assert benchmark._try.__module__ == "bench.io_bench.measure"
    assert benchmark._measure_in_process_rss.__module__ == "bench.io_bench.measure"
    assert benchmark.print_summary.__module__ == "bench.io_bench.reporting"
    assert not hasattr(benchmark, "_measure_rss")
    assert not any(
        isinstance(node, (ast.ClassDef, ast.FunctionDef))
        and node.name
        in {
            "Spec",
            "DirectorySpec",
            "_measure",
            "_try",
            "_measure_rss",
        }
        for node in benchmark_tree.body
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
        for node in ast.walk(benchmark_tree)
    )

    extracted_families = contract["r3_2_family_extraction"]
    for family in extracted_families.values():
        for name, declaration in family["family_functions"].items():
            source_path = ROOT / declaration["source"]
            source_tree = ast.parse(source_path.read_text(encoding="utf-8"))
            matches = [
                node
                for node in source_tree.body
                if isinstance(node, ast.FunctionDef) and node.name == name
            ]
            assert len(matches) == 1
            digest = hashlib.sha256(
                ast.dump(matches[0], include_attributes=False).encode()
            ).hexdigest()
            assert digest == declaration["ast_sha256"]
            source_module = declaration["source"][:-3].replace("/", ".")
            assert getattr(sys.modules[source_module], name).__module__ == (
                source_module
            )
        for name in family["facade_family_exports"]:
            source_module = family["family_functions"][name]["source"][
                :-3
            ].replace("/", ".")
            assert getattr(benchmark, name) is getattr(
                sys.modules[source_module],
                name,
            )
        for name, declaration in family["functions"].items():
            source_path = ROOT / declaration["source"]
            source_tree = ast.parse(source_path.read_text(encoding="utf-8"))
            matches = [
                node
                for node in source_tree.body
                if isinstance(node, ast.FunctionDef) and node.name == name
            ]
            assert len(matches) == 1
            digest = hashlib.sha256(
                ast.dump(matches[0], include_attributes=False).encode()
            ).hexdigest()
            assert digest == declaration["ast_sha256"]
            source_module = declaration["source"][:-3].replace("/", ".")
            assert getattr(benchmark, name).__module__ == source_module
            assert getattr(sys.modules[source_module], name) is getattr(
                benchmark,
                name,
            )
        oracle_module_name = family["optional_oracle_source"][
            :-3
        ].replace("/", ".")
        oracle_module = sys.modules[oracle_module_name]
        for name in family["optional_oracle_bindings"]:
            assert getattr(benchmark, name) is getattr(oracle_module, name)
        for exemption in family["no_oracle_exemptions"].values():
            assert set(exemption) == {
                "unverified_property",
                "verification",
            }
            assert exemption["unverified_property"]
            assert exemption["verification"]

    array_exemptions = extracted_families["arrays"][
        "no_oracle_exemptions"
    ]
    assert set(array_exemptions) == {"flo", "pfm"}
    for exemption in array_exemptions.values():
        assert exemption["unverified_property"] == (
            "independent benchmark encode/decode throughput"
        )
    assert not extracted_families["calibration"][
        "no_oracle_exemptions"
    ]
    image_exemptions = extracted_families["images"][
        "no_oracle_exemptions"
    ]
    assert set(image_exemptions) == {"hdr"}
    assert image_exemptions["hdr"]["unverified_property"] == (
        "portable independent benchmark encode/decode throughput "
        "for Radiance HDR"
    )
    assert image_exemptions["hdr"]["verification"] == (
        "format parity remains covered by the independent NumPy RGBE "
        "parser and serializer in tests/codecs/test_hdr.py"
    )
    assert not extracted_families["meshes"]["no_oracle_exemptions"]
    point_exemptions = extracted_families["points"][
        "no_oracle_exemptions"
    ]
    assert set(point_exemptions) == {"xyz"}
    assert point_exemptions["xyz"]["unverified_property"] == (
        "independent benchmark encode/decode throughput"
    )
    assert point_exemptions["xyz"]["verification"] == (
        "format parity remains covered by the independent NumPy text parser "
        "and serializer in tests/codecs/test_xyz.py"
    )
    reconstruction_exemptions = extracted_families["reconstruction"][
        "no_oracle_exemptions"
    ]
    assert set(reconstruction_exemptions) == {
        "bundler",
        "kitti",
        "nvm",
        "openmvg",
        "transforms_json",
        "tum",
    }
    for exemption in reconstruction_exemptions.values():
        assert exemption["unverified_property"] == (
            "independent benchmark encode/decode throughput"
        )
        assert exemption["verification"].startswith(
            "format parity remains covered by the independent "
        )
    assert extracted_families["reconstruction"][
        "facade_constant_exports"
    ] == ["_EUROC_HEADER"]
    sequence_exemptions = extracted_families["sequences"][
        "no_oracle_exemptions"
    ]
    assert set(sequence_exemptions) == {"image_sequence"}
    assert sequence_exemptions["image_sequence"]["unverified_property"] == (
        "independent benchmark directory encode/decode throughput"
    )
    assert sequence_exemptions["image_sequence"]["verification"] == (
        "format parity remains covered by the independent manifest and "
        "PGM payload fixtures in tests/codecs/test_image_sequence.py"
    )

    lower_modules = sorted(
        {
            declaration["source"][:-3].replace("/", ".")
            for family in extracted_families.values()
            for group in ("family_functions", "functions")
            for declaration in family[group].values()
        }
        | {
            family["optional_oracle_source"][:-3].replace("/", ".")
            for family in extracted_families.values()
        }
    )
    lower_import_probe = textwrap.dedent(
        f"""
        import importlib
        import json
        import sys

        modules = {lower_modules!r}
        for module in modules:
            importlib.import_module(module)
        print(json.dumps({{
            "facade_loaded": "bench.bench_io" in sys.modules,
            "modules": modules,
        }}))
        """
    )
    lower_import_result = subprocess.run(
        [sys.executable, "-c", lower_import_probe],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    lower_import_observed = json.loads(lower_import_result.stdout)
    assert not lower_import_observed["facade_loaded"]
    assert lower_import_observed["modules"] == lower_modules

    calibration_family_module = sys.modules[
        "bench.io_bench.families.calibration"
    ]
    calibration_fixture_module = sys.modules[
        "bench.io_bench.fixtures.calibration"
    ]
    calibration_oracle_module = sys.modules[
        "bench.io_bench.oracles.calibration"
    ]
    assert (
        calibration_family_module._record_nbytes
        is benchmark._record_nbytes
    )
    calibration_specs = benchmark.build_calibration_specs(0.001)
    assert [spec.id for spec in calibration_specs] == [
        "opencv_yaml",
        "opencv_xml",
        "ros_camera_info",
        "kalibr",
    ]
    calibration_by_id = {
        spec.id: spec
        for spec in calibration_specs
    }
    calibration_core_bindings = {
        "opencv_yaml": (
            _core.write_opencv_yaml,
            _core.read_opencv_yaml,
        ),
        "opencv_xml": (
            _core.write_opencv_xml,
            _core.read_opencv_xml,
        ),
        "ros_camera_info": (
            _core.write_ros_camera_info,
            _core.read_ros_camera_info,
        ),
        "kalibr": (
            _core.write_kalibr,
            _core.read_kalibr,
        ),
    }
    for codec_id, bindings in calibration_core_bindings.items():
        spec = calibration_by_id[codec_id]
        assert (spec.w, spec.r) == bindings

    assert (
        calibration_by_id["opencv_yaml"].make
        is calibration_fixture_module._single_calibration
    )
    assert (
        calibration_by_id["opencv_xml"].make
        is calibration_fixture_module._single_calibration
    )
    assert (
        calibration_by_id["ros_camera_info"].make.func
        is calibration_fixture_module._single_calibration
    )
    assert calibration_by_id[
        "ros_camera_info"
    ].make.keywords == {"ros": True}
    assert (
        calibration_by_id["kalibr"].make.func
        is calibration_fixture_module._kalibr_calibration
    )
    assert calibration_by_id["kalibr"].make.args == (0.001,)
    assert (
        calibration_by_id["opencv_xml"].ow,
        calibration_by_id["opencv_xml"].orr,
    ) == (
        calibration_oracle_module._xml_oracle_write,
        calibration_oracle_module._xml_oracle_read,
    )

    yaml_spec_ids = (
        "opencv_yaml",
        "ros_camera_info",
        "kalibr",
    )
    if calibration_oracle_module.yaml is None:
        for codec_id in yaml_spec_ids:
            spec = calibration_by_id[codec_id]
            assert (spec.ow, spec.orr) == (None, None)
    else:
        for codec_id in yaml_spec_ids:
            spec = calibration_by_id[codec_id]
            assert (
                spec.ow,
                spec.orr,
            ) == (
                calibration_oracle_module._yaml_oracle_write,
                calibration_oracle_module._yaml_oracle_read,
            )

    for codec_id, spec in calibration_by_id.items():
        record, payload = spec.make()
        assert spec.nbytes(record, payload) == benchmark._record_nbytes(
            record
        )
        if spec.ow is None or spec.orr is None:
            continue
        decoded = spec.orr(spec.ow(payload))
        if codec_id == "opencv_xml":
            assert decoded.tag == "opencv_storage"
            assert [child.tag for child in decoded] == list(payload)
        else:
            assert decoded == payload

    blocked_calibration_probe = textwrap.dedent(
        """
        import builtins
        import importlib
        import json

        original_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "yaml" or name.startswith("yaml."):
                raise ImportError("blocked by benchmark contract")
            return original_import(name, *args, **kwargs)

        builtins.__import__ = blocked_import
        oracles = importlib.import_module(
            "bench.io_bench.oracles.calibration"
        )
        family = importlib.import_module(
            "bench.io_bench.families.calibration"
        )
        facade = importlib.import_module("bench.bench_io")
        specs = {
            spec.id: spec
            for spec in family.build_calibration_specs(0.001)
        }
        print(json.dumps([
            oracles.yaml is None,
            family.yaml is None,
            facade.yaml is None,
            facade.build_calibration_specs is family.build_calibration_specs,
            facade._yaml_oracle_write is oracles._yaml_oracle_write,
            facade._yaml_oracle_read is oracles._yaml_oracle_read,
            family._yaml_oracle_write is oracles._yaml_oracle_write,
            family._yaml_oracle_read is oracles._yaml_oracle_read,
            specs["opencv_yaml"].ow is None,
            specs["opencv_yaml"].orr is None,
            specs["ros_camera_info"].ow is None,
            specs["ros_camera_info"].orr is None,
            specs["kalibr"].ow is None,
            specs["kalibr"].orr is None,
            specs["opencv_xml"].ow is oracles._xml_oracle_write,
            specs["opencv_xml"].orr is oracles._xml_oracle_read,
        ]))
        """
    )
    blocked_calibration = subprocess.run(
        [sys.executable, "-c", blocked_calibration_probe],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(blocked_calibration.stdout) == [True] * 16

    image_family_module = sys.modules[
        "bench.io_bench.families.images"
    ]
    image_fixture_module = sys.modules[
        "bench.io_bench.fixtures.images"
    ]
    image_oracle_module = sys.modules[
        "bench.io_bench.oracles.images"
    ]
    assert (
        image_family_module._img_u8
        is image_fixture_module._img_u8
    )
    assert (
        image_family_module._img_f32
        is image_fixture_module._img_f32
    )
    for helper_name in (
        "_pil_w",
        "_pil_r",
        "_imageio_w",
        "_imageio_r",
        "_openexr_w",
        "_openexr_r",
    ):
        assert getattr(image_family_module, helper_name) is getattr(
            image_oracle_module,
            helper_name,
        )
    image_specs = benchmark.build_image_specs(0.001)
    assert [spec.id for spec in image_specs] == [
        "png",
        "jpeg",
        "bmp",
        "tga",
        "webp",
        "hdr",
        "exr",
        "netpbm",
    ]
    image_by_id = {spec.id: spec for spec in image_specs}
    image_core_bindings = {
        "png": (_core.write_png, _core.read_png),
        "jpeg": (None, _core.read_jpeg),
        "bmp": (_core.write_bmp, _core.read_bmp),
        "tga": (_core.write_tga, _core.read_tga),
        "webp": (None, _core.read_webp),
        "hdr": (_core.write_hdr, _core.read_hdr),
        "exr": (_core.write_exr, _core.read_exr),
        "netpbm": (None, _core.read_netpbm),
    }
    for codec_id, (writer, reader) in image_core_bindings.items():
        spec = image_by_id[codec_id]
        if writer is not None:
            assert spec.w is writer
        assert spec.r is reader

    image_records = {}
    image_payloads = {}
    for codec_id, spec in image_by_id.items():
        record, payload = spec.make()
        image_records[codec_id] = record
        image_payloads[codec_id] = payload
        assert spec.nbytes(record, payload) == payload.nbytes
        expected_dtype = (
            np.float32
            if codec_id in {"hdr", "exr"}
            else np.uint8
        )
        assert payload.dtype == expected_dtype
        assert payload.ndim == 3
        assert payload.shape[2] == 3

    assert bytes(image_by_id["jpeg"].w(image_records["jpeg"])) == bytes(
        _core.write_jpeg(image_records["jpeg"], 95)
    )
    assert bytes(image_by_id["webp"].w(image_records["webp"])) == bytes(
        _core.write_webp(image_records["webp"], True)
    )
    assert bytes(
        image_by_id["netpbm"].w(image_records["netpbm"])
    ) == bytes(_core.write_netpbm(image_records["netpbm"], False))

    pil_modes = {
        "png": "PNG",
        "jpeg": "JPEG",
        "bmp": "BMP",
        "tga": "TGA",
        "webp": "WEBP",
    }
    if image_oracle_module.PILImage is None:
        for codec_id in pil_modes:
            spec = image_by_id[codec_id]
            assert (spec.ow, spec.orr) == (None, None)
    else:
        for codec_id, mode in pil_modes.items():
            spec = image_by_id[codec_id]
            assert callable(spec.ow)
            assert spec.orr is image_oracle_module._pil_r
            assert spec.ow.__closure__[0].cell_contents == mode

    hdr_spec = image_by_id["hdr"]
    if image_oracle_module.iio is None:
        assert (hdr_spec.ow, hdr_spec.orr) == (None, None)
    else:
        assert callable(hdr_spec.ow)
        assert callable(hdr_spec.orr)
        assert hdr_spec.ow.__closure__[0].cell_contents == ".hdr"
        assert hdr_spec.orr.__closure__[0].cell_contents == ".hdr"

    exr_spec = image_by_id["exr"]
    if image_oracle_module.OpenEXR is None:
        assert (exr_spec.ow, exr_spec.orr) == (None, None)
    else:
        assert (exr_spec.ow, exr_spec.orr) == (
            image_oracle_module._openexr_w,
            image_oracle_module._openexr_r,
        )

    netpbm_spec = image_by_id["netpbm"]
    if image_oracle_module.iio is not None:
        assert callable(netpbm_spec.ow)
        assert callable(netpbm_spec.orr)
        assert netpbm_spec.ow.__closure__[0].cell_contents == ".ppm"
        assert netpbm_spec.orr.__closure__[0].cell_contents == ".ppm"
    elif image_oracle_module.PILImage is not None:
        assert callable(netpbm_spec.ow)
        assert netpbm_spec.orr is image_oracle_module._pil_r
        assert netpbm_spec.ow.__closure__[0].cell_contents == "PPM"
    else:
        assert (netpbm_spec.ow, netpbm_spec.orr) == (None, None)

    def normalized_exr_rgb(decoded):
        if set(decoded) == {"RGB"}:
            rgb = np.asarray(decoded["RGB"])
        else:
            assert set(decoded) == {"B", "G", "R"}
            rgb = np.stack(
                [np.asarray(decoded[channel]) for channel in "RGB"],
                axis=-1,
            )
        return rgb

    def assert_oracle_pixels(codec_id, decoded, payload):
        if codec_id == "exr":
            rgb = normalized_exr_rgb(decoded)
            assert rgb.shape == payload.shape
            np.testing.assert_array_equal(rgb, payload)
            return
        pixels = np.asarray(decoded)
        assert pixels.shape == payload.shape
        assert pixels.dtype == payload.dtype
        if codec_id != "jpeg":
            np.testing.assert_array_equal(pixels, payload)

    for codec_id, spec in image_by_id.items():
        payload = image_payloads[codec_id]
        core_encoded = bytes(spec.w(image_records[codec_id]))
        if codec_id == "hdr":
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                oracle_encoded = (
                    benchmark._try(
                        lambda spec=spec, payload=payload: spec.ow(
                            payload
                        )
                    )
                    if spec.ow is not None
                    else None
                )
                oracle_decoded = (
                    benchmark._try(
                        lambda spec=spec, core_encoded=core_encoded: (
                            spec.orr(core_encoded)
                        )
                    )
                    if spec.orr is not None
                    else None
                )
            if oracle_encoded is not None:
                assert isinstance(oracle_encoded, bytes)
            if oracle_decoded is not None:
                assert np.asarray(oracle_decoded).shape == payload.shape
            continue
        if spec.ow is not None:
            oracle_encoded = spec.ow(payload)
            assert isinstance(oracle_encoded, bytes)
            if spec.orr is not None:
                assert_oracle_pixels(
                    codec_id,
                    spec.orr(oracle_encoded),
                    payload,
                )
        if spec.orr is None:
            continue
        assert_oracle_pixels(
            codec_id,
            spec.orr(core_encoded),
            payload,
        )

    def blocked_image_probe(blocked_roots):
        roots = tuple(blocked_roots)
        probe = textwrap.dedent(
            f"""
            import builtins
            import importlib
            import json

            blocked_roots = {roots!r}
            original_import = builtins.__import__

            def blocked_import(name, *args, **kwargs):
                if any(
                    name == root or name.startswith(root + ".")
                    for root in blocked_roots
                ):
                    raise ImportError("blocked by benchmark contract")
                return original_import(name, *args, **kwargs)

            builtins.__import__ = blocked_import
            oracles = importlib.import_module(
                "bench.io_bench.oracles.images"
            )
            family = importlib.import_module(
                "bench.io_bench.families.images"
            )
            facade = importlib.import_module("bench.bench_io")
            specs = {{
                spec.id: spec
                for spec in family.build_image_specs(0.001)
            }}
            print(json.dumps({{
                "bindings": {{
                    "OpenEXR": oracles.OpenEXR is not None,
                    "PILImage": oracles.PILImage is not None,
                    "iio": oracles.iio is not None,
                }},
                "facade_identity": [
                    facade.OpenEXR is oracles.OpenEXR,
                    facade.PILImage is oracles.PILImage,
                    facade.iio is oracles.iio,
                    facade.build_image_specs is family.build_image_specs,
                ],
                "oracle_pairs": {{
                    codec_id: [
                        spec.ow is not None,
                        spec.orr is not None,
                    ]
                    for codec_id, spec in specs.items()
                }},
                "netpbm_reader_is_pillow": (
                    specs["netpbm"].orr is oracles._pil_r
                ),
            }}))
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    all_images_blocked = blocked_image_probe(
        ("OpenEXR", "PIL", "imageio")
    )
    assert all_images_blocked["bindings"] == {
        "OpenEXR": False,
        "PILImage": False,
        "iio": False,
    }
    assert all(all_images_blocked["facade_identity"])
    assert all(
        pair == [False, False]
        for pair in all_images_blocked["oracle_pairs"].values()
    )

    imageio_blocked = blocked_image_probe(("imageio",))
    assert imageio_blocked["bindings"] == {
        "OpenEXR": True,
        "PILImage": True,
        "iio": False,
    }
    assert imageio_blocked["oracle_pairs"]["hdr"] == [False, False]
    assert imageio_blocked["oracle_pairs"]["netpbm"] == [True, True]
    assert imageio_blocked["netpbm_reader_is_pillow"]

    pillow_blocked = blocked_image_probe(("PIL",))
    assert pillow_blocked["bindings"] == {
        "OpenEXR": True,
        "PILImage": False,
        "iio": True,
    }
    for codec_id in pil_modes:
        assert pillow_blocked["oracle_pairs"][codec_id] == [
            False,
            False,
        ]
    assert pillow_blocked["oracle_pairs"]["netpbm"] == [True, True]

    openexr_blocked = blocked_image_probe(("OpenEXR",))
    assert openexr_blocked["bindings"] == {
        "OpenEXR": False,
        "PILImage": True,
        "iio": True,
    }
    assert openexr_blocked["oracle_pairs"]["exr"] == [False, False]

    mesh_family_module = sys.modules[
        "bench.io_bench.families.meshes"
    ]
    mesh_fixture_module = sys.modules[
        "bench.io_bench.fixtures.meshes"
    ]
    mesh_oracle_module = sys.modules[
        "bench.io_bench.oracles.meshes"
    ]
    mesh_fixture_names = (
        "_mesh_obj",
        "_mesh_off",
        "_mesh_ply",
        "_mesh_scene",
        "_mesh_stl",
    )
    mesh_oracle_names = (
        "_trimesh_glb_r",
        "_trimesh_glb_w",
        "_trimesh_gltf_r",
        "_trimesh_gltf_w",
        "_trimesh_obj_r",
        "_trimesh_obj_w",
        "_trimesh_off_r",
        "_trimesh_off_w",
        "_trimesh_ply_r",
        "_trimesh_ply_w",
        "_trimesh_stl_r",
        "_trimesh_stl_w",
    )
    for helper_name in mesh_fixture_names:
        assert getattr(mesh_family_module, helper_name) is getattr(
            mesh_fixture_module,
            helper_name,
        )
        assert getattr(benchmark, helper_name) is getattr(
            mesh_fixture_module,
            helper_name,
        )
    for helper_name in mesh_oracle_names:
        assert getattr(benchmark, helper_name) is getattr(
            mesh_oracle_module,
            helper_name,
        )
    assert benchmark.trimesh is mesh_oracle_module.trimesh

    mesh_specs = benchmark.build_mesh_specs(0.001)
    assert [spec.id for spec in mesh_specs] == [
        "ply_mesh",
        "obj",
        "stl",
        "off",
        "glb",
    ]
    mesh_core_bindings = {
        "ply_mesh": (_core.write_ply_mesh, _core.read_ply_mesh),
        "obj": (_core.write_obj, _core.read_obj),
        "stl": (_core.write_stl, _core.read_stl),
        "off": (_core.write_off, _core.read_off),
        "glb": (_core.write_glb, _core.read_glb),
    }
    mesh_oracle_bindings = {
        "ply_mesh": (
            mesh_oracle_module._trimesh_ply_w,
            mesh_oracle_module._trimesh_ply_r,
        ),
        "obj": (
            mesh_oracle_module._trimesh_obj_w,
            mesh_oracle_module._trimesh_obj_r,
        ),
        "stl": (
            mesh_oracle_module._trimesh_stl_w,
            mesh_oracle_module._trimesh_stl_r,
        ),
        "off": (
            mesh_oracle_module._trimesh_off_w,
            mesh_oracle_module._trimesh_off_r,
        ),
        "glb": (
            mesh_oracle_module._trimesh_glb_w,
            mesh_oracle_module._trimesh_glb_r,
        ),
    }

    def trimesh_triangles(decoded):
        if hasattr(decoded, "geometry"):
            decoded = decoded.to_geometry()
        vertices = np.asarray(decoded.vertices)
        faces = np.asarray(decoded.faces)
        return vertices[faces]

    def canonical_triangles(triangles):
        triangles = np.asarray(triangles, dtype=np.float64)
        canonical = np.empty_like(triangles)
        for index, triangle in enumerate(triangles):
            rotations = np.stack(
                [
                    triangle,
                    np.roll(triangle, -1, axis=0),
                    np.roll(triangle, -2, axis=0),
                ]
            )
            flattened_rotations = rotations.reshape(3, -1)
            rotation_order = np.lexsort(
                tuple(
                    flattened_rotations[:, component]
                    for component in range(
                        flattened_rotations.shape[1] - 1,
                        -1,
                        -1,
                    )
                )
            )
            canonical[index] = rotations[rotation_order[0]]
        flattened = canonical.reshape(len(canonical), -1)
        face_order = np.lexsort(
            tuple(
                flattened[:, index]
                for index in range(flattened.shape[1] - 1, -1, -1)
            )
        )
        return canonical[face_order]

    def assert_trimesh_geometry(decoded, payload):
        expected = payload["positions"][payload["faces"]]
        np.testing.assert_allclose(
            canonical_triangles(trimesh_triangles(decoded)),
            canonical_triangles(expected),
            rtol=0.0,
            atol=1e-6,
        )

    for spec in mesh_specs:
        assert (spec.w, spec.r) == mesh_core_bindings[spec.id]
        record, payload = spec.make()
        assert spec.nbytes(record, payload) == sum(
            value.nbytes for value in payload.values()
        )
        core_encoded = bytes(spec.w(record))
        assert core_encoded
        spec.r(core_encoded)
        if mesh_oracle_module.trimesh is None:
            assert (spec.ow, spec.orr) == (None, None)
            continue
        assert (spec.ow, spec.orr) == mesh_oracle_bindings[spec.id]
        oracle_encoded = spec.ow(payload)
        assert isinstance(oracle_encoded, bytes)
        assert oracle_encoded
        assert_trimesh_geometry(spec.orr(oracle_encoded), payload)
        assert_trimesh_geometry(spec.orr(core_encoded), payload)

    if mesh_oracle_module.trimesh is not None:
        gltf_record, gltf_payload = mesh_fixture_module._mesh_scene(9)
        oracle_files = mesh_oracle_module._trimesh_gltf_w(
            gltf_payload
        )
        assert isinstance(oracle_files, dict)
        assert oracle_files
        assert all(
            isinstance(name, str) and isinstance(data, bytes)
            for name, data in oracle_files.items()
        )
        assert_trimesh_geometry(
            mesh_oracle_module._trimesh_gltf_r(oracle_files),
            gltf_payload,
        )
        document, binary = _core.write_gltf(
            gltf_record,
            "mesh.bin",
        )
        core_files = {
            "scene.gltf": bytes(document),
            "mesh.bin": bytes(binary),
        }
        assert_trimesh_geometry(
            mesh_oracle_module._trimesh_gltf_r(core_files),
            gltf_payload,
        )

    blocked_mesh_probe = textwrap.dedent(
        f"""
        import builtins
        import importlib
        import json

        original_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "trimesh" or name.startswith("trimesh."):
                raise ImportError("blocked by benchmark contract")
            return original_import(name, *args, **kwargs)

        builtins.__import__ = blocked_import
        oracles = importlib.import_module(
            "bench.io_bench.oracles.meshes"
        )
        fixtures = importlib.import_module(
            "bench.io_bench.fixtures.meshes"
        )
        family = importlib.import_module(
            "bench.io_bench.families.meshes"
        )
        facade = importlib.import_module("bench.bench_io")
        specs = family.build_mesh_specs(0.001)
        fixture_names = {mesh_fixture_names!r}
        oracle_names = {mesh_oracle_names!r}
        print(json.dumps([
            oracles.trimesh is None,
            family.trimesh is oracles.trimesh,
            facade.trimesh is oracles.trimesh,
            facade.build_mesh_specs is family.build_mesh_specs,
            all(
                getattr(family, name) is getattr(fixtures, name)
                and getattr(facade, name) is getattr(fixtures, name)
                for name in fixture_names
            ),
            all(
                getattr(facade, name) is getattr(oracles, name)
                for name in oracle_names
            ),
            all(
                spec.ow is None and spec.orr is None
                for spec in specs
            ),
        ]))
        """
    )
    blocked_mesh = subprocess.run(
        [sys.executable, "-c", blocked_mesh_probe],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(blocked_mesh.stdout) == [True] * 7

    point_family_module = sys.modules[
        "bench.io_bench.families.points"
    ]
    point_fixture_module = sys.modules[
        "bench.io_bench.fixtures.points"
    ]
    point_oracle_module = sys.modules[
        "bench.io_bench.oracles.points"
    ]
    point_fixture_names = ("_pc", "_pc_laz", "_pc_ply")
    point_oracle_names = (
        "_laspy_laz_w",
        "_laspy_r",
        "_laspy_w",
        "_open3d_pcd_r",
        "_open3d_pcd_w",
        "_open3d_ply_r",
        "_open3d_ply_w",
        "_pts_oracle_read",
        "_pts_oracle_write",
    )
    for helper_name in point_fixture_names:
        assert getattr(point_family_module, helper_name) is getattr(
            point_fixture_module,
            helper_name,
        )
        assert getattr(benchmark, helper_name) is getattr(
            point_fixture_module,
            helper_name,
        )
    for helper_name in point_oracle_names:
        assert getattr(point_family_module, helper_name) is getattr(
            point_oracle_module,
            helper_name,
        )
        assert getattr(benchmark, helper_name) is getattr(
            point_oracle_module,
            helper_name,
        )
    assert benchmark.laspy is point_oracle_module.laspy
    assert benchmark.o3d is point_oracle_module.o3d

    point_specs = benchmark.build_point_specs(0.001)
    assert [spec.id for spec in point_specs] == [
        "xyz",
        "pts",
        "ply",
        "pcd",
        "las",
        "laz",
    ]
    point_by_id = {spec.id: spec for spec in point_specs}
    assert extracted_families["points"]["benchmark_equivalence_repairs"] == {
        "las_laz": {
            "issue": (
                "LASpy previously encoded XYZ-only LAS point format 0 "
                "while SceneIO encoded point format 2 with XYZ, RGB, "
                "and intensity"
            ),
            "verification": (
                "LAS and LAZ now use one XYZ, RGB, and intensity payload "
                "on both sides and retain one positions-equivalent "
                "throughput denominator"
            ),
        }
    }
    point_core_bindings = {
        "xyz": (_core.write_xyz, _core.read_xyz),
        "pts": (_core.write_pts, _core.read_pts),
        "ply": (_core.write_ply, _core.read_ply),
        "pcd": (_core.write_pcd, _core.read_pcd),
        "las": (None, _core.read_las),
        "laz": (None, _core.read_laz),
    }
    point_records = {}
    point_payloads = {}
    point_core_bytes = {}
    for spec in point_specs:
        writer, reader = point_core_bindings[spec.id]
        if writer is not None:
            assert spec.w is writer
        assert spec.r is reader
        record, payload = spec.make()
        point_records[spec.id] = record
        point_payloads[spec.id] = payload
        expected_nbytes = (
            payload["positions"].nbytes
            if spec.id in {"las", "laz"}
            else (
                sum(value.nbytes for value in payload.values())
                if isinstance(payload, dict)
                else payload.nbytes
            )
        )
        assert spec.nbytes(record, payload) == expected_nbytes
        encoded = bytes(spec.w(record))
        assert encoded
        point_core_bytes[spec.id] = encoded
        spec.r(encoded)

    assert bytes(point_by_id["las"].w(point_records["las"])) == bytes(
        _core.write_las(point_records["las"], 0.001)
    )
    assert bytes(point_by_id["laz"].w(point_records["laz"])) == bytes(
        _core.write_laz(point_records["laz"], 0.001)
    )
    assert (
        point_by_id["xyz"].ow,
        point_by_id["xyz"].orr,
    ) == (None, None)

    pts_spec = point_by_id["pts"]
    assert (pts_spec.ow, pts_spec.orr) == (
        point_oracle_module._pts_oracle_write,
        point_oracle_module._pts_oracle_read,
    )
    pts_oracle_bytes = pts_spec.ow(point_payloads["pts"])
    assert isinstance(pts_oracle_bytes, bytes)
    np.testing.assert_array_equal(
        pts_spec.orr(pts_oracle_bytes),
        point_payloads["pts"],
    )
    np.testing.assert_array_equal(
        pts_spec.orr(point_core_bytes["pts"]),
        point_payloads["pts"],
    )

    open3d_bindings = {
        "ply": (
            point_oracle_module._open3d_ply_w,
            point_oracle_module._open3d_ply_r,
        ),
        "pcd": (
            point_oracle_module._open3d_pcd_w,
            point_oracle_module._open3d_pcd_r,
        ),
    }

    def assert_open3d_cloud(decoded, payload):
        np.testing.assert_allclose(
            np.asarray(decoded.points),
            payload["positions"],
            rtol=0.0,
            atol=1e-6,
        )
        np.testing.assert_allclose(
            np.asarray(decoded.normals),
            payload["normals"],
            rtol=0.0,
            atol=1e-6,
        )
        np.testing.assert_allclose(
            np.asarray(decoded.colors) * 255.0,
            payload["colors"],
            rtol=0.0,
            atol=1e-6,
        )

    for codec_id, expected_pair in open3d_bindings.items():
        spec = point_by_id[codec_id]
        if point_oracle_module.o3d is None:
            assert (spec.ow, spec.orr) == (None, None)
            continue
        assert (spec.ow, spec.orr) == expected_pair
        oracle_encoded = spec.ow(point_payloads[codec_id])
        assert isinstance(oracle_encoded, bytes)
        assert_open3d_cloud(
            spec.orr(oracle_encoded),
            point_payloads[codec_id],
        )
        assert_open3d_cloud(
            spec.orr(point_core_bytes[codec_id]),
            point_payloads[codec_id],
        )

    laspy_bindings = {
        "las": (
            point_oracle_module._laspy_w,
            point_oracle_module._laspy_r,
        ),
        "laz": (
            point_oracle_module._laspy_laz_w,
            point_oracle_module._laspy_r,
        ),
    }

    def assert_laspy_cloud(codec_id, decoded):
        payload = point_payloads[codec_id]
        assert decoded.header.point_format.id == 2
        np.testing.assert_allclose(
            np.asarray(decoded.xyz),
            payload["positions"],
            rtol=0.0,
            atol=0.00051,
        )
        np.testing.assert_array_equal(
            np.column_stack(
                (decoded.red, decoded.green, decoded.blue)
            ),
            payload["colors16"],
        )
        np.testing.assert_array_equal(
            np.asarray(decoded.intensity),
            payload["intensity"],
        )

    for codec_id, expected_pair in laspy_bindings.items():
        spec = point_by_id[codec_id]
        if point_oracle_module.laspy is None:
            assert (spec.ow, spec.orr) == (None, None)
            continue
        assert (spec.ow, spec.orr) == expected_pair
        oracle_encoded = spec.ow(point_payloads[codec_id])
        assert isinstance(oracle_encoded, bytes)
        if codec_id == "las":
            assert len(oracle_encoded) == len(point_core_bytes[codec_id])
        assert_laspy_cloud(codec_id, spec.orr(oracle_encoded))
        assert_laspy_cloud(
            codec_id,
            spec.orr(point_core_bytes[codec_id]),
        )

    def blocked_point_probe(blocked_roots):
        roots = tuple(blocked_roots)
        probe = textwrap.dedent(
            f"""
            import builtins
            import importlib
            import json

            blocked_roots = {roots!r}
            original_import = builtins.__import__

            def blocked_import(name, *args, **kwargs):
                if any(
                    name == root or name.startswith(root + ".")
                    for root in blocked_roots
                ):
                    raise ImportError("blocked by benchmark contract")
                return original_import(name, *args, **kwargs)

            builtins.__import__ = blocked_import
            oracles = importlib.import_module(
                "bench.io_bench.oracles.points"
            )
            fixtures = importlib.import_module(
                "bench.io_bench.fixtures.points"
            )
            family = importlib.import_module(
                "bench.io_bench.families.points"
            )
            facade = importlib.import_module("bench.bench_io")
            specs = {{
                spec.id: spec
                for spec in family.build_point_specs(0.001)
            }}
            fixture_names = {point_fixture_names!r}
            oracle_names = {point_oracle_names!r}
            print(json.dumps({{
                "bindings": {{
                    "laspy": oracles.laspy is not None,
                    "o3d": oracles.o3d is not None,
                }},
                "identities": [
                    facade.laspy is oracles.laspy,
                    facade.o3d is oracles.o3d,
                    facade.build_point_specs is family.build_point_specs,
                    all(
                        getattr(family, name) is getattr(fixtures, name)
                        and getattr(facade, name) is getattr(fixtures, name)
                        for name in fixture_names
                    ),
                    all(
                        getattr(family, name) is getattr(oracles, name)
                        and getattr(facade, name) is getattr(oracles, name)
                        for name in oracle_names
                    ),
                ],
                "oracle_pairs": {{
                    codec_id: [
                        spec.ow is not None,
                        spec.orr is not None,
                    ]
                    for codec_id, spec in specs.items()
                }},
            }}))
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    all_point_libraries_blocked = blocked_point_probe(
        ("laspy", "open3d")
    )
    assert all_point_libraries_blocked["bindings"] == {
        "laspy": False,
        "o3d": False,
    }
    assert all(all_point_libraries_blocked["identities"])
    assert all_point_libraries_blocked["oracle_pairs"] == {
        "xyz": [False, False],
        "pts": [True, True],
        "ply": [False, False],
        "pcd": [False, False],
        "las": [False, False],
        "laz": [False, False],
    }

    open3d_blocked = blocked_point_probe(("open3d",))
    assert open3d_blocked["bindings"] == {
        "laspy": True,
        "o3d": False,
    }
    assert open3d_blocked["oracle_pairs"]["ply"] == [False, False]
    assert open3d_blocked["oracle_pairs"]["pcd"] == [False, False]
    assert open3d_blocked["oracle_pairs"]["las"] == [True, True]
    assert open3d_blocked["oracle_pairs"]["laz"] == [True, True]

    laspy_blocked = blocked_point_probe(("laspy",))
    assert laspy_blocked["bindings"] == {
        "laspy": False,
        "o3d": True,
    }
    assert laspy_blocked["oracle_pairs"]["ply"] == [True, True]
    assert laspy_blocked["oracle_pairs"]["pcd"] == [True, True]
    assert laspy_blocked["oracle_pairs"]["las"] == [False, False]
    assert laspy_blocked["oracle_pairs"]["laz"] == [False, False]

    array_oracle_module = sys.modules["bench.io_bench.oracles.arrays"]
    oracle_probe = np.arange(12, dtype=np.float32).reshape(3, 4)
    np.testing.assert_array_equal(
        benchmark._np_r(benchmark._np_w(oracle_probe)),
        oracle_probe,
    )
    npz_probe = {
        "a": oracle_probe,
        "b": np.arange(5, dtype=np.int16),
    }
    loaded_npz = benchmark._load_npz_oracle(
        benchmark._save_npz_oracle(npz_probe)
    )
    assert set(loaded_npz) == set(npz_probe)
    for name, expected in npz_probe.items():
        np.testing.assert_array_equal(loaded_npz[name], expected)
    np.testing.assert_array_equal(
        benchmark._dmb_oracle_read(
            benchmark._dmb_oracle_write(oracle_probe)
        ),
        oracle_probe,
    )

    safetensors_bindings = [
        benchmark.safetensors_load,
        benchmark.safetensors_load_file,
        benchmark.safetensors_open,
        benchmark.safetensors_save,
        benchmark.safetensors_save_file,
    ]
    if importlib.util.find_spec("safetensors") is None:
        assert all(binding is None for binding in safetensors_bindings)
    else:
        assert all(callable(binding) for binding in safetensors_bindings)
        encoded = benchmark.safetensors_save(npz_probe)
        loaded = benchmark.safetensors_load(encoded)
        for name, expected in npz_probe.items():
            np.testing.assert_array_equal(loaded[name], expected)
        with tempfile.TemporaryDirectory(
            prefix="sceneio_bench_oracle_"
        ) as directory:
            path = Path(directory) / "probe.safetensors"
            benchmark.safetensors_save_file(npz_probe, path)
            loaded_file = benchmark.safetensors_load_file(path)
            for name, expected in npz_probe.items():
                np.testing.assert_array_equal(loaded_file[name], expected)
            with benchmark.safetensors_open(path, framework="np") as handle:
                assert tuple(handle.keys()) == tuple(sorted(npz_probe))
                for name, expected in npz_probe.items():
                    np.testing.assert_array_equal(
                        handle.get_tensor(name),
                        expected,
                    )

    array_specs = benchmark.build_array_specs(0.001)
    assert [spec.id for spec in array_specs] == [
        "npy",
        "pfm",
        "flo",
        "dmb",
        "npz",
        "safetensors",
    ]
    by_id = {spec.id: spec for spec in array_specs}
    expected_core_bindings = {
        "npy": (_core.write_npy, _core.read_npy),
        "pfm": (_core.write_pfm, _core.read_pfm),
        "flo": (_core.write_flo, _core.read_flo),
        "dmb": (_core.write_dmb, _core.read_dmb),
        "npz": (_core.write_npz, _core.read_npz),
        "safetensors": (
            _core.write_safetensors,
            _core.read_safetensors,
        ),
    }
    for codec_id, bindings in expected_core_bindings.items():
        assert (by_id[codec_id].w, by_id[codec_id].r) == bindings
    assert (by_id["npy"].ow, by_id["npy"].orr) == (
        array_oracle_module._np_w,
        array_oracle_module._np_r,
    )
    assert (by_id["pfm"].ow, by_id["pfm"].orr) == (None, None)
    assert (by_id["flo"].ow, by_id["flo"].orr) == (None, None)
    assert (by_id["dmb"].ow, by_id["dmb"].orr) == (
        array_oracle_module._dmb_oracle_write,
        array_oracle_module._dmb_oracle_read,
    )
    assert callable(by_id["npz"].ow)
    assert by_id["npz"].ow.__module__ == (
        "bench.io_bench.families.arrays"
    )
    assert by_id["npz"].orr is array_oracle_module._load_npz_oracle

    for codec_id in ("npy", "dmb", "npz"):
        spec = by_id[codec_id]
        assert spec.ow is not None
        assert spec.orr is not None
        unused_record, payload = spec.make()
        decoded = spec.orr(spec.ow(payload))
        if codec_id == "npz":
            assert set(decoded) == set(payload)
            for name, expected in payload.items():
                np.testing.assert_array_equal(decoded[name], expected)
        else:
            np.testing.assert_array_equal(decoded, payload)

    safetensors_spec = by_id["safetensors"]
    if callable(array_oracle_module.safetensors_save):
        assert callable(safetensors_spec.ow)
        assert (
            safetensors_spec.orr
            is array_oracle_module.safetensors_load
        )
        unused_record, payload = safetensors_spec.make()
        decoded = safetensors_spec.orr(safetensors_spec.ow(payload))
        assert set(decoded) == set(payload)
        for name, expected in payload.items():
            np.testing.assert_array_equal(decoded[name], expected)
    else:
        assert (safetensors_spec.ow, safetensors_spec.orr) == (None, None)

    blocked_probe = textwrap.dedent(
        """
        import builtins
        import importlib
        import json

        original_import = builtins.__import__

        def blocked_import(name, *args, **kwargs):
            if name == "safetensors" or name.startswith("safetensors."):
                raise ImportError("blocked by benchmark contract")
            return original_import(name, *args, **kwargs)

        builtins.__import__ = blocked_import
        oracles = importlib.import_module(
            "bench.io_bench.oracles.arrays"
        )
        family = importlib.import_module(
            "bench.io_bench.families.arrays"
        )
        facade = importlib.import_module("bench.bench_io")
        specs = {
            spec.id: spec
            for spec in family.build_array_specs(0.001)
        }
        print(json.dumps([
            oracles.safetensors_load is None,
            oracles.safetensors_load_file is None,
            oracles.safetensors_open is None,
            oracles.safetensors_save is None,
            oracles.safetensors_save_file is None,
            family.safetensors_load is None,
            family.safetensors_save is None,
            facade.safetensors_load is None,
            facade.safetensors_load_file is None,
            facade.safetensors_open is None,
            facade.safetensors_save is None,
            facade.safetensors_save_file is None,
            specs["safetensors"].ow is None,
            specs["safetensors"].orr is None,
        ]))
        """
    )
    blocked = subprocess.run(
        [sys.executable, "-c", blocked_probe],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(blocked.stdout) == [True] * 14

    reconstruction_family_module = sys.modules[
        "bench.io_bench.families.reconstruction"
    ]
    reconstruction_fixture_module = sys.modules[
        "bench.io_bench.fixtures.reconstruction"
    ]
    reconstruction_oracle_module = sys.modules[
        "bench.io_bench.oracles.reconstruction"
    ]
    reconstruction_fixture_names = (
        "_bal_fixture",
        "_euroc_fixture",
        "_g2o_fixture",
        "_poses_and_reconstruction",
    )
    reconstruction_oracle_names = (
        "_bal_oracle_read",
        "_bal_oracle_write",
        "_euroc_oracle_read",
        "_euroc_oracle_write",
        "_g2o_oracle_read",
        "_g2o_oracle_write",
    )
    reconstruction_size_names = (
        "_bal_payload_nbytes",
        "_euroc_payload_nbytes",
        "_g2o_payload_nbytes",
    )
    for helper_name in reconstruction_fixture_names:
        assert getattr(reconstruction_family_module, helper_name) is getattr(
            reconstruction_fixture_module,
            helper_name,
        )
        assert getattr(benchmark, helper_name) is getattr(
            reconstruction_fixture_module,
            helper_name,
        )
    for helper_name in reconstruction_oracle_names:
        assert getattr(
            reconstruction_family_module, helper_name
        ) is getattr(reconstruction_oracle_module, helper_name)
        assert getattr(benchmark, helper_name) is getattr(
            reconstruction_oracle_module,
            helper_name,
        )
    for helper_name in reconstruction_size_names:
        assert getattr(benchmark, helper_name) is getattr(
            reconstruction_family_module,
            helper_name,
        )
    assert benchmark._EUROC_HEADER is (
        reconstruction_oracle_module._EUROC_HEADER
    )
    assert benchmark.build_reconstruction_specs is (
        reconstruction_family_module.build_reconstruction_specs
    )

    pose_bundle = benchmark._poses_and_reconstruction(0.001)
    reconstruction_specs = benchmark.build_reconstruction_specs(
        0.001, pose_bundle
    )
    assert [spec.id for spec in reconstruction_specs] == [
        "transforms_json",
        "tum",
        "kitti",
        "euroc_state",
        "g2o",
        "bundler",
        "bal",
        "nvm",
        "openmvg",
    ]
    reconstruction_by_id = {
        spec.id: spec for spec in reconstruction_specs
    }
    reconstruction_core_bindings = {
        "transforms_json": (
            _core.write_transforms_json,
            _core.read_transforms_json,
        ),
        "tum": (_core.write_tum, _core.read_tum),
        "kitti": (_core.write_kitti, _core.read_kitti),
        "euroc_state": (
            _core.write_euroc_state,
            _core.read_euroc_state,
        ),
        "g2o": (_core.write_g2o, _core.read_g2o),
        "bundler": (_core.write_bundler, _core.read_bundler),
        "bal": (_core.write_bal, _core.read_bal),
        "nvm": (_core.write_nvm, _core.read_nvm),
        "openmvg": (_core.write_openmvg, _core.read_openmvg),
    }
    reconstruction_payloads = {}
    reconstruction_core_bytes = {}
    for spec in reconstruction_specs:
        writer, reader = reconstruction_core_bindings[spec.id]
        assert spec.w is writer
        assert spec.r is reader
        record, payload = spec.make()
        reconstruction_payloads[spec.id] = payload
        expected_nbytes = (
            sum(value.nbytes for value in payload.values())
            if isinstance(payload, dict)
            else benchmark._record_nbytes(record)
        )
        assert spec.nbytes(record, payload) == expected_nbytes
        encoded = bytes(spec.w(record))
        assert encoded
        reconstruction_core_bytes[spec.id] = encoded
        spec.r(encoded)

    for codec_id in extracted_families["reconstruction"][
        "no_oracle_exemptions"
    ]:
        spec = reconstruction_by_id[codec_id]
        assert (spec.ow, spec.orr) == (None, None)

    euroc_spec = reconstruction_by_id["euroc_state"]
    euroc_payload = reconstruction_payloads["euroc_state"]
    euroc_expected_states = np.concatenate(
        (
            euroc_payload["positions"],
            euroc_payload["quaternions"],
            euroc_payload["velocities"],
            euroc_payload["gyro_biases"],
            euroc_payload["accel_biases"],
        ),
        axis=1,
    )
    for encoded in (
        euroc_spec.ow(euroc_payload),
        reconstruction_core_bytes["euroc_state"],
    ):
        decoded = euroc_spec.orr(encoded)
        np.testing.assert_array_equal(
            decoded["timestamps"], euroc_payload["timestamps"]
        )
        np.testing.assert_allclose(
            decoded["states"], euroc_expected_states, rtol=0.0, atol=0.0
        )

    g2o_spec = reconstruction_by_id["g2o"]
    g2o_payload = reconstruction_payloads["g2o"]
    for encoded in (
        g2o_spec.ow(g2o_payload),
        reconstruction_core_bytes["g2o"],
    ):
        decoded = g2o_spec.orr(encoded)
        for name in (
            "node_ids",
            "node_translations",
            "node_quaternions",
            "edge_endpoints",
            "edge_translations",
            "edge_quaternions",
            "information_matrices",
        ):
            np.testing.assert_allclose(
                decoded[name], g2o_payload[name], rtol=0.0, atol=0.0
            )
        np.testing.assert_array_equal(
            decoded["fixed_node_ids"],
            g2o_payload["node_ids"][g2o_payload["fixed"] != 0],
        )

    bal_spec = reconstruction_by_id["bal"]
    bal_payload = reconstruction_payloads["bal"]
    for encoded in (
        bal_spec.ow(bal_payload),
        reconstruction_core_bytes["bal"],
    ):
        decoded = bal_spec.orr(encoded)
        np.testing.assert_allclose(
            decoded["observations"][:, :2],
            np.column_stack(
                (
                    bal_payload["camera_indices"],
                    bal_payload["point_indices"],
                )
            ),
            rtol=0.0,
            atol=0.0,
        )
        np.testing.assert_allclose(
            decoded["observations"][:, 2:],
            bal_payload["observations"],
            rtol=0.0,
            atol=0.0,
        )
        np.testing.assert_allclose(
            decoded["cameras"],
            bal_payload["cameras"],
            rtol=0.0,
            atol=0.0,
        )
        np.testing.assert_allclose(
            decoded["points"],
            bal_payload["points"],
            rtol=0.0,
            atol=0.0,
        )

    lower_reconstruction_probe = textwrap.dedent(
        """
        import importlib
        import json
        import sys

        oracles = importlib.import_module(
            "bench.io_bench.oracles.reconstruction"
        )
        fixtures = importlib.import_module(
            "bench.io_bench.fixtures.reconstruction"
        )
        family = importlib.import_module(
            "bench.io_bench.families.reconstruction"
        )
        print(json.dumps([
            "bench.bench_io" not in sys.modules,
            family._poses_and_reconstruction
                is fixtures._poses_and_reconstruction,
            family._euroc_oracle_write is oracles._euroc_oracle_write,
            [spec.id for spec in family.build_reconstruction_specs(0.001)],
        ]))
        """
    )
    lower_reconstruction = subprocess.run(
        [sys.executable, "-c", lower_reconstruction_probe],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(lower_reconstruction.stdout) == [
        True,
        True,
        True,
        [
            "transforms_json",
            "tum",
            "kitti",
            "euroc_state",
            "g2o",
            "bundler",
            "bal",
            "nvm",
            "openmvg",
        ],
    ]

    sequence_family_module = sys.modules[
        "bench.io_bench.families.sequences"
    ]
    sequence_fixture_module = sys.modules[
        "bench.io_bench.fixtures.sequences"
    ]
    sequence_oracle_module = sys.modules[
        "bench.io_bench.oracles.sequences"
    ]
    assert benchmark.build_sequence_specs is (
        sequence_family_module.build_sequence_specs
    )
    assert benchmark._y4m_fixture is (
        sequence_fixture_module._y4m_fixture
    )
    assert benchmark._image_sequence_directory_fixture is (
        sequence_fixture_module._image_sequence_directory_fixture
    )
    assert benchmark._y4m_oracle_write is (
        sequence_oracle_module._y4m_oracle_write
    )
    assert benchmark._y4m_oracle_read is (
        sequence_oracle_module._y4m_oracle_read
    )

    sequence_specs = benchmark.build_sequence_specs(0.001)
    assert [spec.id for spec in sequence_specs] == ["y4m"]
    y4m_spec = sequence_specs[0]
    assert (y4m_spec.w, y4m_spec.r) == (
        _core.write_y4m,
        _core.read_y4m,
    )
    assert (y4m_spec.ow, y4m_spec.orr) == (
        sequence_oracle_module._y4m_oracle_write,
        sequence_oracle_module._y4m_oracle_read,
    )
    y4m_record, y4m_payload = y4m_spec.make()
    assert y4m_spec.nbytes(y4m_record, y4m_payload) == sum(
        value.nbytes for value in y4m_payload.values()
    )
    y4m_core_bytes = bytes(y4m_spec.w(y4m_record))
    y4m_oracle_bytes = y4m_spec.ow(y4m_payload)
    y4m_metadata = {
        "width": y4m_record.width,
        "height": y4m_record.height,
        "frame_rate": (
            y4m_record.frame_rate_numerator,
            y4m_record.frame_rate_denominator,
        ),
        "pixel_aspect": (
            y4m_record.pixel_aspect_numerator,
            y4m_record.pixel_aspect_denominator,
        ),
        "chroma_subsampling": y4m_record.chroma_subsampling,
        "chroma_siting": y4m_record.chroma_siting,
        "color_range": y4m_record.color_range,
        "matrix": y4m_record.matrix,
        "interlace": y4m_record.interlace,
    }
    for encoded in (y4m_core_bytes, y4m_oracle_bytes):
        decoded = y4m_spec.orr(encoded)
        for name, expected in y4m_payload.items():
            np.testing.assert_array_equal(decoded[name], expected)
        assert {
            name: decoded[name] for name in y4m_metadata
        } == y4m_metadata
    y4m_core_record = y4m_spec.r(y4m_oracle_bytes)
    for name, expected in y4m_payload.items():
        np.testing.assert_array_equal(
            np.asarray(getattr(y4m_core_record, name)),
            expected,
        )
    assert {
        "width": y4m_core_record.width,
        "height": y4m_core_record.height,
        "frame_rate": (
            y4m_core_record.frame_rate_numerator,
            y4m_core_record.frame_rate_denominator,
        ),
        "pixel_aspect": (
            y4m_core_record.pixel_aspect_numerator,
            y4m_core_record.pixel_aspect_denominator,
        ),
        "chroma_subsampling": y4m_core_record.chroma_subsampling,
        "chroma_siting": y4m_core_record.chroma_siting,
        "color_range": y4m_core_record.color_range,
        "matrix": y4m_core_record.matrix,
        "interlace": y4m_core_record.interlace,
    } == y4m_metadata

    with tempfile.TemporaryDirectory(
        prefix="sceneio_bench_sequence_"
    ) as directory:
        root = Path(directory)
        directory_specs = benchmark._directory_specs(None, 0.001, root)
        image_sequence_spec = next(
            spec for spec in directory_specs if spec.id == "image_sequence"
        )
        assert image_sequence_spec.make.func is (
            sequence_fixture_module._image_sequence_directory_fixture
        )
        image_sequence_record, logical_size = image_sequence_spec.make()
        assert logical_size == image_sequence_spec.nbytes(
            image_sequence_record,
            logical_size,
        )
        assert image_sequence_record.num_frames == 32
        assert (
            image_sequence_record.height,
            image_sequence_record.width,
            image_sequence_record.channels,
            image_sequence_record.frame_dtype,
        ) == (8, 8, 3, "uint8")
        assert all(
            Path(path).is_absolute()
            for path in image_sequence_record.frame_paths
        )
        destination = root / "output"
        image_sequence_spec.w(image_sequence_record, destination)
        decoded_sequence = image_sequence_spec.r(destination)
        assert decoded_sequence.frame_names == (
            image_sequence_record.frame_names
        )
        np.testing.assert_array_equal(
            decoded_sequence.timestamps_ns,
            image_sequence_record.timestamps_ns,
        )
        np.testing.assert_array_equal(
            decoded_sequence.durations_ns,
            image_sequence_record.durations_ns,
        )
        assert (
            decoded_sequence.height,
            decoded_sequence.width,
            decoded_sequence.channels,
            decoded_sequence.frame_dtype,
        ) == (8, 8, 3, "uint8")
        assert decoded_sequence.frame_paths == [
            str((destination / name).resolve())
            for name in decoded_sequence.frame_names
        ]
        for source, name in zip(
            image_sequence_record.frame_paths,
            image_sequence_record.frame_names,
            strict=True,
        ):
            assert (destination / name).read_bytes() == Path(
                source
            ).read_bytes()

    lower_sequence_probe = textwrap.dedent(
        """
        import importlib
        import json
        import sys

        oracles = importlib.import_module(
            "bench.io_bench.oracles.sequences"
        )
        fixtures = importlib.import_module(
            "bench.io_bench.fixtures.sequences"
        )
        family = importlib.import_module(
            "bench.io_bench.families.sequences"
        )
        print(json.dumps([
            "bench.bench_io" not in sys.modules,
            family._y4m_fixture is fixtures._y4m_fixture,
            family._y4m_oracle_write is oracles._y4m_oracle_write,
            [spec.id for spec in family.build_sequence_specs(0.001)],
        ]))
        """
    )
    lower_sequence = subprocess.run(
        [sys.executable, "-c", lower_sequence_probe],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(lower_sequence.stdout) == [
        True,
        True,
        True,
        ["y4m"],
    ]

    calls = []
    duration, peak = benchmark._measure(
        lambda: calls.append(len(calls)),
        runs=2,
    )
    assert len(calls) == 4  # warm, two timing calls, one traced call
    assert duration >= 0
    assert peak >= 0
    assert benchmark._try(lambda: "ok") == "ok"

    def fail():
        raise RuntimeError("expected")

    assert benchmark._try(fail) is None
    measurement_module = sys.modules["bench.io_bench.measure"]
    original_psutil = measurement_module.psutil
    unavailable_call_count = 0

    def unavailable_operation():
        nonlocal unavailable_call_count
        unavailable_call_count += 1

    try:
        measurement_module.psutil = None
        assert benchmark._measure_in_process_rss(unavailable_operation) == 0
    finally:
        measurement_module.psutil = original_psutil
    assert unavailable_call_count == 0

    reporting_output = io.StringIO()
    with contextlib.redirect_stdout(reporting_output):
        benchmark.print_primary_header()
        benchmark.print_primary_row(
            "codec_x",
            1.25,
            0.5,
            10,
            20,
            30,
            None,
            40,
            1.1,
            0.2,
            3.3,
            0.4,
            0.5,
        )
        benchmark.print_typed_adapter(
            {
                "format": "png",
                "read_mbps": 12.4,
                "write_mbps": 5.6,
                "inspect_ms": 0.1234,
                "read_peak_mb": 0.0012,
                "write_peak_mb": 0.0034,
            }
        )
        benchmark.print_encoding_variants(
            "PLY",
            {
                "ascii": {"write_mbps": 1.2, "read_mbps": 3.4},
                "binary": {"write_mbps": 5.6, "read_mbps": 7.8},
            },
        )
        benchmark.print_colmap_db_row(
            (1.0, 2.0, 3.0, 4.0, None, 6.0, 0.7, 0.8)
        )
        benchmark.print_directory_row(
            "directory",
            1.0,
            2.0,
            3.0,
            4.0,
            5.0,
            0.6,
            0.7,
        )
        try:
            raise ValueError("broken")
        except ValueError as error:
            benchmark.print_primary_error("failed", error)
        benchmark.print_summary(
            [("fmt", 1.0, 2.0, None, 3.0, None, 0.4, None, 0.5)],
            [("fmt", "operation", 2.0, 3.0, "bytes")],
            [("fmt", 0.010, 0.002, 1.0, 0.2, 3.0, 0.4)],
            [("fmt", 0.010, 0.004, 1.0, 0.3, 3.0, 0.5)],
        )
        benchmark.print_regression_guard_passed()
        benchmark.print_cold_cache_unavailable()
        benchmark.print_json_result({"codec": "large", "value": 1})
    assert reporting_output.getvalue() == (
        CONTRACTS / "bench_io_reporting_v1.txt"
    ).read_text(encoding="utf-8")
    assert contract["metric_semantics"] == {
        "json_fields": "*_rss_mb",
        "implementation_name": "in_process_rss",
        "scope": "warmed_parent_process_peak_rss_delta",
        "qualification_role": "exploratory_not_fresh_process_evidence",
        "unavailable_json_value_mb": 0,
    }


def _assert_benchmark_representative_fixtures_match_checked_fingerprints():
    contract = _read_json("bench_io_v1.json")
    fingerprint_contract = contract["representative_fixture_fingerprints"]
    assert fingerprint_contract["algorithm"] == "sha256-canonical-fixture-v1"
    builder_sources = fingerprint_contract["builder_ast_sources"]
    assert sorted(builder_sources) == fingerprint_contract[
        "builder_ast_functions"
    ]
    builder_nodes = {}
    for name, relative_path in builder_sources.items():
        source_path = ROOT / relative_path
        assert source_path.is_relative_to(ROOT / "bench")
        source_tree = ast.parse(source_path.read_text(encoding="utf-8"))
        matches = [
            node
            for node in source_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        ]
        assert len(matches) == 1
        builder_nodes[name] = matches[0]
    assert sorted(builder_nodes) == fingerprint_contract["builder_ast_functions"]
    builder_payload = "\n".join(
        ast.dump(builder_nodes[name], include_attributes=False)
        for name in sorted(builder_nodes)
    )
    assert hashlib.sha256(builder_payload.encode()).hexdigest() == (
        fingerprint_contract["current_builder_ast_sha256"]
    )
    benchmark = _load_benchmark_module("sceneio_bench_fixtures")

    image, _ = benchmark._img_u8(8, 8)
    sequence, _ = benchmark._y4m_fixture(8)
    point_cloud, _ = benchmark._pc_ply(16)
    mesh_scene, _ = benchmark._mesh_scene(9)
    gaussian_cloud, _ = benchmark._gauss(16)
    calibration, _ = benchmark._single_calibration()
    specs = benchmark._specs(0.001)
    tensors, _ = next(spec for spec in specs if spec.id == "npz").make()
    reconstruction = benchmark._poses_and_reconstruction(0.001)[0]
    reconstruction_payload = {
        "cameras": [
            _record_projection(
                camera,
                ("id", "model", "width", "height", "params"),
            )
            for camera in reconstruction.cameras
        ],
        **_record_projection(
            reconstruction,
            (
                "image_ids",
                "image_camera_ids",
                "image_names",
                "point3D_ids",
                "xyz",
                "rgb",
                "errors",
                "quaternions",
                "translations",
                "pose_convention",
                "quaternion_order",
            ),
        ),
    }
    fixtures = {
        "image_rgb8": _record_projection(
            image,
            (
                "pixels",
                "width",
                "height",
                "channels",
                "dtype",
                "color_space",
                "channel_order",
                "row_order",
                "alpha_mode",
                "maxval",
            ),
        ),
        "image_sequence_yuv420": _record_projection(
            sequence,
            (
                "y",
                "u",
                "v",
                "timestamps_ns",
                "durations_ns",
                "frame_names",
                "frame_paths",
                "width",
                "height",
                "channels",
                "num_frames",
                "storage_mode",
                "frame_dtype",
                "color_space",
                "alpha_mode",
                "has_chroma",
                "chroma_subsampling",
                "chroma_siting",
                "color_range",
                "matrix",
                "interlace",
                "frame_rate_numerator",
                "frame_rate_denominator",
                "pixel_aspect_numerator",
                "pixel_aspect_denominator",
            ),
        ),
        "point_cloud_ply": _record_projection(
            point_cloud,
            (
                "positions",
                "normals",
                "colors",
                "colors16",
                "intensities",
                "num_points",
                "coordinate_frame",
                "scale_to_meters",
                "origin",
                "viewpoint",
                "width",
                "height",
                "is_organized",
                "intensity_range",
                "has_normals",
                "has_rgb",
                "has_rgb16",
                "has_intensity",
            ),
        ),
        "mesh_scene": {
            **_record_projection(
                mesh_scene,
                (
                    "mesh_primitive_offsets",
                    "mesh_names",
                    "node_meshes",
                    "node_child_offsets",
                    "node_children",
                    "node_local_transforms",
                    "node_names",
                    "scene_root_offsets",
                    "scene_roots",
                    "scene_names",
                    "default_scene",
                    "num_meshes",
                    "num_primitives",
                    "num_nodes",
                    "num_scenes",
                    "has_materials",
                ),
            ),
            "primitives": [
                _record_projection(
                    mesh_scene.primitive_at(index),
                    (
                        "positions",
                        "face_offsets",
                        "face_indices",
                        "vertex_normals",
                        "vertex_uvs",
                        "vertex_colors",
                        "primitive_offsets",
                        "primitive_materials",
                        "coordinate_frame",
                        "scale_to_meters",
                        "local_transform",
                    ),
                )
                for index in range(mesh_scene.num_primitives)
            ],
        },
        "gaussian_cloud": _record_projection(
            gaussian_cloud,
            (
                "means",
                "scales",
                "quaternions",
                "opacities",
                "sh_dc",
                "sh_rest",
                "num_gaussians",
                "num_rest",
                "sh_degree",
                "scale_space",
                "opacity_space",
                "quaternion_order",
                "sh_layout",
            ),
        ),
        "camera_calibration": _record_projection(
            calibration,
            (
                "camera_ids",
                "resolutions",
                "projection_models",
                "intrinsic_offsets",
                "intrinsics",
                "distortion_models",
                "distortion_offsets",
                "distortion_coefficients",
                "quaternions",
                "translations",
                "has_extrinsics",
                "names",
                "camera_matrices",
                "has_camera_matrix",
                "rectification_matrices",
                "has_rectification",
                "projection_matrices",
                "has_projection_matrix",
                "binning",
                "roi",
                "roi_do_rectify",
                "has_operational",
                "time_offsets",
                "has_time_offset",
                "topics",
                "axis_frame",
                "reference_frame",
                "scale_to_meters",
                "quaternion_order",
                "quaternion_sign",
                "transform_convention",
                "time_offset_convention",
            ),
        ),
        "tensor_dict": {
            "arrays": dict(tensors.items()),
            "attrs": tensors.attrs,
            "byte_order": tensors.byte_order,
            "order": tensors.order,
        },
        "reconstruction": reconstruction_payload,
    }
    assert {
        name: _fixture_fingerprint(value)
        for name, value in fixtures.items()
    } == fingerprint_contract["fixtures"]


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

    benchmark_path = ROOT / "bench" / "bench_io.py"
    direct = subprocess.run(
        [sys.executable, str(benchmark_path), "--help"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert direct.stdout.startswith("usage: bench_io.py")
    canonical_probe = textwrap.dedent(
        f"""
        import importlib.util
        import pathlib
        import sys

        path = pathlib.Path({str(benchmark_path)!r})
        spec = importlib.util.spec_from_file_location("bench.bench_io", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        print(module.Spec.__module__)
        """
    )
    canonical = subprocess.run(
        [sys.executable, "-c", canonical_probe],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert canonical.stdout.strip() == "bench.io_bench.model"


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
