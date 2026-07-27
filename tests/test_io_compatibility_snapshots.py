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
import textwrap
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
    benchmark_tree = ast.parse(
        (ROOT / "bench" / "bench_io.py").read_text(encoding="utf-8")
    )
    builder_nodes = {
        node.name: node
        for node in benchmark_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in fingerprint_contract["builder_ast_functions"]
    }
    assert sorted(builder_nodes) == fingerprint_contract["builder_ast_functions"]
    builder_payload = "\n".join(
        ast.dump(builder_nodes[name], include_attributes=False)
        for name in sorted(builder_nodes)
    )
    assert hashlib.sha256(builder_payload.encode()).hexdigest() == (
        fingerprint_contract["parent_and_candidate_builder_ast_sha256"]
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
