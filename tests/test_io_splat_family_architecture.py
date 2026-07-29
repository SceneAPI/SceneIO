"""Architecture and exact-parent behavior contracts for the splat family."""

from __future__ import annotations

import ast
import base64
import copy
import gc
import gzip
import hashlib
import importlib
import inspect
import io
import json
import os
import platform
import shutil
import struct
import subprocess
import sys
import textwrap
import tomllib
import tracemalloc
import zipfile
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
from sceneio.io._inspectors import splats as splat_inspector
from sceneio.io._registry import assembly
from sceneio.io._registry.families import splats as splat_family

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = json.loads(
    (ROOT / "tests/contracts/io_splat_family_v1.json").read_text(
        encoding="utf-8"
    )
)
BENCHMARK_EVIDENCE = json.loads(
    (ROOT / "tests/contracts/io_splat_benchmark_parent_v1.json").read_text(
        encoding="utf-8"
    )
)
SPLAT_IDS = FAMILY_MEMBERS["splats"]
PARTIAL_IDS = tuple(value for value in SPLAT_IDS if value != "spz")
SUFFIXES = {
    "gaussian_ply": ".ply",
    "compressed_ply": ".compressed.ply",
    "sog": ".sog",
    "ksplat": ".ksplat",
    "spz": ".spz",
    "splat": ".splat",
}
INSPECTOR_NAMES = {
    "gaussian_ply": "inspect_gaussian_ply",
    "compressed_ply": "inspect_compressed_ply",
    "sog": "inspect_sog",
    "ksplat": "inspect_ksplat",
    "spz": "inspect_spz",
    "splat": "inspect_splat",
}


def _cloud():
    means = (
        np.arange(24, dtype=np.float32).reshape(8, 3) - np.float32(10)
    ) / np.float32(4)
    scales = np.linspace(-1.0, 0.75, 24, dtype=np.float32).reshape(8, 3)
    quaternions = np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.5, 0.5, 0.5, 0.5],
            [1.0, 1.0, 0.0, 0.0],
            [1.0, 0.0, 1.0, 0.0],
            [1.0, 0.0, 0.0, 1.0],
            [2.0, -1.0, 0.5, 0.25],
            [0.25, 0.5, -0.75, 1.0],
            [1.0, -1.0, 1.0, -1.0],
        ],
        dtype=np.float32,
    )
    opacities = np.linspace(-2.0, 2.0, 8, dtype=np.float32)
    sh_dc = np.linspace(-0.75, 0.75, 24, dtype=np.float32).reshape(8, 3)
    return _core.gaussian_cloud(
        means,
        scales,
        quaternions,
        opacities,
        sh_dc,
    )


def _write_valid(root: Path) -> dict[str, Path]:
    cloud = _cloud()
    paths = {}
    for format_id in SPLAT_IDS:
        path = root / f"valid{SUFFIXES[format_id]}"
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


def _record_fingerprint(cloud) -> str:
    fields = []
    for name in (
        "means",
        "scales",
        "quaternions",
        "opacities",
        "sh_dc",
        "sh_rest",
    ):
        value = np.asarray(getattr(cloud, name))
        canonical = np.ascontiguousarray(
            value.astype(value.dtype.newbyteorder("<"), copy=False)
        )
        fields.append(
            [
                name,
                str(value.dtype),
                list(value.shape),
                hashlib.sha256(canonical.tobytes()).hexdigest(),
            ]
        )
    payload = json.dumps(
        {
            "num_gaussians": cloud.num_gaussians,
            "sh_degree": cloud.sh_degree,
            "num_rest": cloud.num_rest,
            "quaternion_order": cloud.quaternion_order,
            "scale_space": cloud.scale_space,
            "opacity_space": cloud.opacity_space,
            "sh_layout": cloud.sh_layout,
            "fields": fields,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _active_parent_profile() -> str | None:
    profiles = CONTRACT["platform_evidence"]["profiles"]
    explicit = os.environ.get("SCENEIO_SPLAT_PARENT_PROFILE")
    if explicit is not None:
        assert explicit in profiles, (
            "unknown SCENEIO_SPLAT_PARENT_PROFILE: " + explicit
        )
        return explicit
    machine = platform.machine().lower()
    if sys.platform == "win32" and machine in {"amd64", "x86_64"}:
        return "windows_msvc_x86_64"
    if sys.platform == "darwin" and machine in {"arm64", "aarch64"}:
        return "macos_appleclang_arm64"
    return None


def _profile_record_hashes(contract_name: str) -> dict[str, str]:
    return {
        profile: evidence["record_sha256"][contract_name]
        for profile, evidence in CONTRACT["platform_evidence"][
            "profiles"
        ].items()
    }


def _field_sha256(value) -> str:
    array = np.asarray(value)
    canonical = np.ascontiguousarray(
        array.astype(array.dtype.newbyteorder("<"), copy=False)
    )
    return hashlib.sha256(canonical.tobytes()).hexdigest()


def _assert_portable_record(cloud, contract_name: str) -> None:
    contract = CONTRACT["decoded_record_contracts"][contract_name]
    actual_record_sha256 = _record_fingerprint(cloud)
    profile_hashes = _profile_record_hashes(contract_name)
    profile = _active_parent_profile()
    if profile is None:
        assert actual_record_sha256 in set(profile_hashes.values()), {
            "actual": actual_record_sha256,
            "known_parent_variants": profile_hashes,
        }
    else:
        assert actual_record_sha256 == profile_hashes[profile], {
            "profile": profile,
            "actual": actual_record_sha256,
            "expected": profile_hashes[profile],
        }

    assert {
        "num_gaussians": cloud.num_gaussians,
        "sh_degree": cloud.sh_degree,
        "num_rest": cloud.num_rest,
        "quaternion_order": cloud.quaternion_order,
        "scale_space": cloud.scale_space,
        "opacity_space": cloud.opacity_space,
        "sh_layout": cloud.sh_layout,
    } == {
        "num_gaussians": 8,
        "sh_degree": 0,
        "num_rest": 0,
        "quaternion_order": "wxyz",
        "scale_space": "log",
        "opacity_space": "logit",
        "sh_layout": "channel_grouped",
    }
    for name, expected_sha256 in contract[
        "exact_field_sha256"
    ].items():
        value = np.asarray(getattr(cloud, name))
        assert np.isfinite(value).all()
        assert _field_sha256(value) == expected_sha256, name

    ulp = contract["ulp_field"]
    actual = np.asarray(getattr(cloud, ulp["name"]))
    expected_dtype = np.dtype(ulp["dtype"])
    assert actual.dtype == expected_dtype
    assert list(actual.shape) == ulp["shape"]
    assert np.isfinite(actual).all()
    expected = np.frombuffer(
        base64.b64decode(ulp["canonical_base64"]),
        dtype=expected_dtype.newbyteorder("<"),
    ).reshape(ulp["shape"])
    np.testing.assert_array_max_ulp(
        actual,
        expected,
        maxulp=ulp["max_ulp"],
    )
    zero = actual == 0
    np.testing.assert_array_equal(
        np.signbit(actual[zero]),
        np.signbit(expected[zero]),
    )


def _assert_sog_metadata(metadata: bytes) -> tuple[str, str]:
    parsed = json.loads(metadata)
    metadata_sha256 = hashlib.sha256(metadata).hexdigest()
    means_min_z_hex = float(parsed["means"]["mins"][2]).hex()
    encoding = CONTRACT["sog_encoding_contract"]
    assert metadata_sha256 == encoding["metadata_sha256"]
    assert means_min_z_hex == encoding["means_min_z_hex"]
    return metadata_sha256, means_min_z_hex


def _assert_sog_profile(
    *,
    archive_sha256: str | None,
    metadata_sha256: str,
    means_min_z_hex: str,
) -> None:
    observed = {
        "sog_metadata_sha256": metadata_sha256,
        "sog_means_min_z_hex": means_min_z_hex,
    }
    if archive_sha256 is not None:
        observed["sog_archive_sha256"] = archive_sha256
    encoding = CONTRACT["sog_encoding_contract"]
    expected = {
        "sog_metadata_sha256": encoding["metadata_sha256"],
        "sog_means_min_z_hex": encoding["means_min_z_hex"],
    }
    if archive_sha256 is not None:
        expected["sog_archive_sha256"] = CONTRACT["valid"]["sog"][
            "sha256"
        ]
    assert observed == expected


def _assert_sog_archive(payload: bytes) -> None:
    archive_sha256 = hashlib.sha256(payload).hexdigest()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        infos = archive.infolist()
        assert [value.filename for value in infos] == CONTRACT[
            "sog_encoding_contract"
        ]["members"]
        assert all(value.compress_type == zipfile.ZIP_STORED for value in infos)
        metadata = archive.read("meta.json")
        for info in infos:
            if info.filename == "meta.json":
                continue
            expected = CONTRACT["valid"]["sog_directory"]["files"][
                info.filename
            ]
            member = archive.read(info)
            assert len(member) == expected["byte_size"]
            assert hashlib.sha256(member).hexdigest() == expected["sha256"]
    metadata_sha256, means_min_z_hex = _assert_sog_metadata(metadata)
    _assert_sog_profile(
        archive_sha256=archive_sha256,
        metadata_sha256=metadata_sha256,
        means_min_z_hex=means_min_z_hex,
    )


def _callable_descriptor(value):
    if value is None:
        return None
    result = {
        "module": value.__module__,
        "qualname": value.__qualname__,
    }
    nonlocals = inspect.getclosurevars(value).nonlocals
    if nonlocals:
        result["nonlocals"] = {
            key: (
                f"{item.__module__}.{item.__name__}"
                if callable(item)
                else item
            )
            for key, item in nonlocals.items()
        }
    return result


def _codec_descriptor(codec) -> dict[str, object]:
    return {
        "id": codec.id,
        "extensions": list(codec.extensions),
        "record": codec.record.__name__,
        "datatype": codec.datatype,
        "magic": [value.hex() for value in codec.magic],
        "filenames": list(codec.filenames),
        "is_directory": codec.is_directory,
        "dir_marker": codec.dir_marker,
        "lossy": codec.lossy,
        "container_kind": codec.container_kind,
        "streams_read": codec.streams_read,
        "streams_write": codec.streams_write,
        "requires_features": list(codec.requires_features),
        "supported_features": list(codec.supported_features),
        "unsupported_features": list(codec.unsupported_features),
        "read": _callable_descriptor(codec.read),
        "write": _callable_descriptor(codec.write),
        "inspect": _callable_descriptor(codec.inspect),
        "read_window": _callable_descriptor(codec.read_window),
        "read_points": _callable_descriptor(codec.read_points),
        "read_faces": _callable_descriptor(codec.read_faces),
        "read_mesh": _callable_descriptor(codec.read_mesh),
        "read_primitive": _callable_descriptor(codec.read_primitive),
        "read_states": _callable_descriptor(codec.read_states),
        "read_frames": _callable_descriptor(codec.read_frames),
        "read_image": _callable_descriptor(codec.read_image),
        "read_pair": _callable_descriptor(codec.read_pair),
        "read_tensors": _callable_descriptor(codec.read_tensors),
        "read_slices": _callable_descriptor(codec.read_slices),
    }


def _codec_ast_hashes() -> dict[str, str]:
    paths = [
        ROOT / "src/sceneio/io/registry.py",
        ROOT / "src/sceneio/io/_registry/families/splats.py",
    ]
    hashes = {}
    for path in paths:
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Codec"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in SPLAT_IDS
            ):
                assert node.args[0].value not in hashes
                payload = ast.dump(
                    copy.deepcopy(node),
                    annotate_fields=True,
                    include_attributes=False,
                )
                hashes[node.args[0].value] = hashlib.sha256(
                    payload.encode()
                ).hexdigest()
    return hashes


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


def _assert_cloud_slice(selected, full, start: int, stop: int) -> None:
    for name in (
        "means",
        "scales",
        "quaternions",
        "opacities",
        "sh_dc",
        "sh_rest",
    ):
        np.testing.assert_array_equal(
            np.asarray(getattr(selected, name)),
            np.asarray(getattr(full, name))[start:stop],
        )
    assert selected.sh_degree == full.sh_degree
    assert selected.num_rest == full.num_rest
    assert selected.quaternion_order == full.quaternion_order
    assert selected.scale_space == full.scale_space
    assert selected.opacity_space == full.opacity_space
    assert selected.sh_layout == full.sh_layout


def test_splat_parent_contract_metadata_is_exact():
    assert CONTRACT["schema_version"] == 1
    assert CONTRACT["parent"] == {
        "commit": "0696533e515b5f8e65cbb676df28d852f9d0a049",
        "tree": "62a844b198dfd05d5d6d435a8e2aa22bf6bb898e",
    }
    assert tuple(CONTRACT["family_ids"]) == SPLAT_IDS
    assert CONTRACT["canonical_positions"] == {
        format_id: CANONICAL_BUILTIN_IDS.index(format_id)
        for format_id in SPLAT_IDS
    }
    benchmark = CONTRACT["benchmark_parent"]
    assert benchmark["captures"] == BENCHMARK_EVIDENCE["capture_count"] == 2
    assert benchmark["platform"] == BENCHMARK_EVIDENCE[
        "capture_platform"
    ] == "windows-msvc"
    assert benchmark["projection_artifact"] == (
        "tests/contracts/io_splat_benchmark_parent_v1.json"
    )
    assert BENCHMARK_EVIDENCE["source_parent_commit"] == CONTRACT["parent"][
        "commit"
    ]
    assert BENCHMARK_EVIDENCE["capture_argv"] == [
        ".venv/Scripts/python.exe",
        "bench/bench_io.py",
        "--runs",
        "1",
        "--scale",
        "0.001",
        "--skip-oracles",
        "--json",
        "<output>",
    ]
    assert [row["codec"] for row in BENCHMARK_EVIDENCE["rows"]] == list(
        SPLAT_IDS
    )
    payload = json.dumps(
        BENCHMARK_EVIDENCE["rows"],
        sort_keys=True,
        separators=(",", ":"),
    )
    assert hashlib.sha256(payload.encode()).hexdigest() == benchmark[
        "splat_rows_projection_sha256"
    ]
    assembly_contract = json.loads(
        (
            ROOT / "tests/contracts/io_registry_assembly_v1.json"
        ).read_text(encoding="utf-8")
    )
    assert benchmark["all_codec_projection_sha256"] == assembly_contract[
        "benchmark_parent"
    ]["structural_projection_sha256"]
    assert CONTRACT["pytest_parent_collection"] == {
        "count": 3256,
        "sorted_normalized_node_ids_sha256": (
            "156a06a5fb3b801073253892d9d584f8a9dcb230ccd42babf056b2a020c71347"
        ),
    }
    assert CONTRACT["focused_parent_collection"] == {
        "gaussian_ply": 5,
        "compressed_ply": 21,
        "sog": 28,
        "ksplat": 35,
        "spz": 13,
        "splat": 11,
    }
    assert set(CONTRACT["platform_evidence"]["profiles"]) == {
        "windows_msvc_x86_64",
        "macos_appleclang_arm64",
        "ubuntu_latest_x86_64_glibc",
        "manylinux2014_gcc10_x86_64",
    }
    assert set(CONTRACT["decoded_record_contracts"]) == {
        "ksplat",
        "spz_v3_v4",
        "splat",
    }
    evidence = CONTRACT["platform_evidence"]
    assert evidence["exposing_commit"] == (
        "93fcf1b39350a3a0080a7b87ead65d0d9343d354"
    )
    assert evidence["hosted_run"] == 30220612832
    windows = evidence["profiles"]["windows_msvc_x86_64"]
    historical_sog = {
        profile_name: (
            profile["sog_archive_sha256"],
            profile["sog_metadata_sha256"],
            profile["sog_means_min_z_hex"],
        )
        for profile_name, profile in evidence["profiles"].items()
    }
    windows_sog = (
        "037a5837afeabe3a7ff6fc8988cadfbd5fecf3f47dd93e3cdfb8e1e24b0b2a55",
        "4c3c9560b4355ec1d1cb6c1a4b827ededf9deb7c7a9c8a12ed89768cdbb292a4",
        "-0x1.193ea7aad030bp+0",
    )
    linux_sog = (
        "c2c08d4636c8a560b9fe18c16469b20f49747a0b516da52a07f3dcdf87bd8cc8",
        "312a1b0a0c1f9d5c9ffca7db770f6673f933b249ea580ead9bad34b1a2177c2d",
        "-0x1.193ea7aad030ap+0",
    )
    assert historical_sog == {
        "windows_msvc_x86_64": windows_sog,
        "macos_appleclang_arm64": windows_sog,
        "ubuntu_latest_x86_64_glibc": linux_sog,
        "manylinux2014_gcc10_x86_64": linux_sog,
    }
    ubuntu = evidence["profiles"]["ubuntu_latest_x86_64_glibc"]
    assert CONTRACT["valid"]["sog"]["sha256"] == ubuntu[
        "sog_archive_sha256"
    ]
    assert CONTRACT["sog_encoding_contract"]["metadata_sha256"] == ubuntu[
        "sog_metadata_sha256"
    ]
    assert CONTRACT["sog_encoding_contract"]["means_min_z_hex"] == ubuntu[
        "sog_means_min_z_hex"
    ]
    assert CONTRACT["valid"]["sog_directory"]["files"]["meta.json"][
        "sha256"
    ] == ubuntu["sog_metadata_sha256"]
    assert {
        "ksplat": CONTRACT["valid"]["ksplat"]["record_sha256"],
        "spz_v3_v4": CONTRACT["valid"]["spz"]["record_sha256"],
        "splat": CONTRACT["valid"]["splat"]["record_sha256"],
    } == windows["record_sha256"]
    assert CONTRACT["valid"]["spz_v4"]["record_sha256"] == windows[
        "record_sha256"
    ]["spz_v3_v4"]


def test_splat_codec_definitions_match_parent_ast_and_descriptors():
    assert tuple(registry.REGISTRY) == CANONICAL_BUILTIN_IDS
    assert _codec_ast_hashes() == CONTRACT["codec_ast_sha256"]
    for format_id in SPLAT_IDS:
        codec = registry.REGISTRY[format_id]
        position = CONTRACT["canonical_positions"][format_id]
        assert registry.BUILTIN_DEFINITIONS[position] is codec
        descriptor = json.dumps(
            _codec_descriptor(codec),
            sort_keys=True,
            separators=(",", ":"),
        )
        assert hashlib.sha256(descriptor.encode()).hexdigest() == CONTRACT[
            "codec_descriptor_sha256"
        ][format_id]


def test_splat_definitions_preserve_order_positions_and_identity():
    definitions = registry._SPLAT_CODECS
    assert isinstance(definitions, tuple)
    assert tuple(codec.id for codec in definitions) == SPLAT_IDS
    assert tuple(registry.REGISTRY) == CANONICAL_BUILTIN_IDS
    assert CONTRACT["canonical_positions"] == {
        format_id: CANONICAL_BUILTIN_IDS.index(format_id)
        for format_id in SPLAT_IDS
    }
    for codec in definitions:
        position = CONTRACT["canonical_positions"][codec.id]
        assert registry.REGISTRY[codec.id] is codec
        assert registry.BUILTIN_DEFINITIONS[position] is codec


def test_splat_family_is_staged_once_and_not_defined_inline():
    source = inspect.getsource(registry)
    tree = ast.parse(source)
    staging = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_define_builtin_family"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "splats"
    ]
    assert len(staging) == 1
    assert (
        source.count(
            "_SPLAT_CODECS = build_splat_codecs(\n"
            "    _sog_reader,\n"
            "    _sog_writer,\n"
            "    _sog_point_reader,\n"
            ")"
        )
        == 1
    )
    assert (
        source.count('_define_builtin_family("splats", _SPLAT_CODECS)') == 1
    )
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Codec"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            assert node.args[0].value not in SPLAT_IDS


def test_splat_family_module_is_lower_layer_only():
    source = inspect.getsource(splat_family)
    imports = _absolute_imports(source)
    assert {module for module, _ in imports} <= {
        "__future__",
        "sceneio",
        "sceneio.io._registry.adapters",
        "sceneio.io._registry.model",
    }
    assert tuple(
        names for module, names in imports if module == "sceneio"
    ) == (("_core",),)
    for forbidden in (
        "sceneio.io.registry",
        "sceneio.io._inspection",
        "sceneio.io._registry.assembly",
        "REGISTRY",
        "register(",
    ):
        assert forbidden not in source


def test_splat_family_staging_is_atomic_and_recoverable():
    definitions = registry._SPLAT_CODECS
    builder = assembly.BuiltinAssembly(SPLAT_IDS)
    with pytest.raises(ValueError, match="do not match"):
        builder.add_family("splats", tuple(reversed(definitions)))
    assert builder.add_family("splats", definitions) is definitions
    finalized = builder.finalize()
    assert finalized == definitions
    assert builder.finalize() is finalized

    builder = assembly.BuiltinAssembly(SPLAT_IDS)
    invalid = (*definitions[:-1], object())
    with pytest.raises(TypeError, match="family entries"):
        builder.add_family("splats", invalid)
    assert builder.add_family("splats", definitions) is definitions
    assert builder.finalize() == definitions


def test_splat_family_reload_is_inert_and_registry_reload_is_exact():
    code = textwrap.dedent(
        """
        import importlib
        import tempfile
        from pathlib import Path

        import sceneio.io as public_io
        from sceneio.io import registry
        from sceneio.io._builtin_manifest import (
            CANONICAL_BUILTIN_IDS,
            FAMILY_MEMBERS,
        )
        from sceneio.io._registry.families import splats

        before_registry = registry.REGISTRY
        assert public_io.REGISTRY is before_registry
        before_items = tuple(registry.REGISTRY.items())
        before_codecs = registry._SPLAT_CODECS
        reloaded_family = importlib.reload(splats)
        assert registry.REGISTRY is before_registry
        assert tuple(registry.REGISTRY.items()) == before_items
        assert registry._SPLAT_CODECS is before_codecs

        fresh = reloaded_family.build_splat_codecs(
            registry._sog_reader,
            registry._sog_writer,
            registry._sog_point_reader,
        )
        assert tuple(codec.id for codec in fresh) == FAMILY_MEMBERS["splats"]
        assert all(registry.REGISTRY[codec.id] is not codec for codec in fresh)

        original_builder = splats.build_splat_codecs

        def fail_build(*args):
            raise RuntimeError("injected splat family failure")

        splats.build_splat_codecs = fail_build
        try:
            try:
                importlib.reload(registry)
            except RuntimeError as exc:
                assert str(exc) == "injected splat family failure"
            else:
                raise AssertionError("injected registry reload unexpectedly passed")
        finally:
            splats.build_splat_codecs = original_builder
        assert registry.REGISTRY is before_registry
        assert public_io.REGISTRY is before_registry
        assert tuple(registry.REGISTRY.items()) == before_items
        assert public_io.get("sog") is dict(before_items)["sog"]
        assert public_io.codecs()["sog"] is dict(before_items)["sog"]

        for _ in range(2):
            reloaded_registry = importlib.reload(registry)
            assert reloaded_registry.REGISTRY is before_registry
            assert public_io.REGISTRY is reloaded_registry.REGISTRY
            assert tuple(reloaded_registry.REGISTRY) == CANONICAL_BUILTIN_IDS
            assert tuple(
                codec.id for codec in reloaded_registry._SPLAT_CODECS
            ) == FAMILY_MEMBERS["splats"]
            for codec in reloaded_registry._SPLAT_CODECS:
                assert reloaded_registry.REGISTRY[codec.id] is codec
            assert public_io.get("sog") is public_io.codecs()["sog"]
            assert (
                public_io.capabilities("sog")
                == public_io.get("sog").capabilities()
            )

        extension = reloaded_registry.Codec(
            "reload_probe",
            (".reload-probe",),
            lambda path: path,
            None,
            None,
            "probe",
        )
        assert public_io.register(extension) is extension
        assert public_io.REGISTRY["reload_probe"] is extension
        assert public_io.get("reload_probe") is extension
        assert public_io.codecs()["reload_probe"] is extension
        assert public_io.capabilities("reload_probe").format == "reload_probe"

        reloaded_registry = importlib.reload(registry)
        assert reloaded_registry.REGISTRY is before_registry
        assert public_io.REGISTRY is reloaded_registry.REGISTRY
        assert tuple(reloaded_registry.REGISTRY)[
            : len(CANONICAL_BUILTIN_IDS)
        ] == CANONICAL_BUILTIN_IDS
        assert reloaded_registry.REGISTRY["reload_probe"] is extension
        assert public_io.get("reload_probe") is extension
        assert public_io.codecs()["reload_probe"] is extension
        assert public_io.capabilities("reload_probe").format == "reload_probe"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.reload-probe"
            path.write_bytes(b"probe")
            assert public_io.detect(path) == "reload_probe"
        """
    )
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)


def test_splat_operation_identities_and_native_targets_are_exact():
    for format_id in SPLAT_IDS:
        assert registry.REGISTRY[format_id].record is _core.GaussianCloud

    sog = registry.REGISTRY["sog"]
    assert sog.read is registry._sog_reader
    assert sog.write is registry._sog_writer
    assert sog.read_points is registry._sog_point_reader

    ordinary = (
        "gaussian_ply",
        "compressed_ply",
        "ksplat",
        "spz",
        "splat",
    )
    for format_id in ordinary:
        codec = registry.REGISTRY[format_id]
        assert inspect.getclosurevars(codec.read).nonlocals == {
            "fn": getattr(_core, f"read_{format_id}")
        }
        assert inspect.getclosurevars(codec.write).nonlocals == {
            "fn": getattr(_core, f"write_{format_id}"),
            "prepare": None,
        }
    for format_id in (
        "gaussian_ply",
        "compressed_ply",
        "ksplat",
        "splat",
    ):
        assert inspect.getclosurevars(
            registry.REGISTRY[format_id].read_points
        ).nonlocals == {
            "fn": getattr(_core, f"read_{format_id}_points")
        }
    assert registry.REGISTRY["spz"].read_points is None


def test_splat_inspector_module_is_lower_layer_only():
    source = inspect.getsource(splat_inspector)
    imports = _absolute_imports(source)
    assert {module for module, _ in imports} <= {
        "__future__",
        "gzip",
        "numpy",
        "pathlib",
        "sceneio",
        "sceneio.io._inspectors.common",
        "sceneio.io._inspectors.model",
        "sceneio.io._ply",
        "struct",
        "zipfile",
    }
    assert tuple(
        names for module, names in imports if module == "sceneio"
    ) == (("_core",),)
    for forbidden in (
        "sceneio.io.registry",
        "sceneio.io._inspection",
        "sceneio.io._registry",
        "REGISTRY",
        "register(",
    ):
        assert forbidden not in source
    for format_id in SPLAT_IDS:
        assert f"_core.read_{format_id}" not in source
        assert f"_core.write_{format_id}" not in source


def test_splat_inspector_reload_is_inert():
    before_registry = registry.REGISTRY
    before_items = tuple(registry.REGISTRY.items())
    reloaded = importlib.reload(splat_inspector)
    assert reloaded is splat_inspector
    assert registry.REGISTRY is before_registry
    assert tuple(registry.REGISTRY.items()) == before_items


@pytest.mark.parametrize(
    ("wrapper_name", "delegate_name"),
    [
        ("_inspect_gaussian_ply", "_inspect_splat_gaussian_ply"),
        ("_inspect_compressed_ply", "_inspect_splat_compressed_ply"),
        ("_inspect_sog", "_inspect_splat_sog"),
        ("_inspect_ksplat", "_inspect_splat_ksplat"),
        ("_inspect_spz", "_inspect_splat_spz"),
        ("_inspect_splat", "_inspect_splat_splat"),
    ],
)
def test_splat_inspector_facade_preserves_wrapper_signatures(
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
    path = Path("splat.fixture")
    wrapper = getattr(_inspection, wrapper_name)
    assert tuple(inspect.signature(wrapper).parameters) == (
        "path",
        "datatype",
    )
    assert wrapper(path, "splat") is marker
    assert calls == [(path, "splat")]


def test_repository_coverage_tracks_all_splat_inspectors():
    coverage = tomllib.loads(
        (
            ROOT / "tests" / "contracts" / "repository_coverage_v1.toml"
        ).read_text(encoding="utf-8")
    )
    owners = {
        item["id"]: item["inspection_source"]
        for item in coverage["codec"]
        if item["id"] in SPLAT_IDS
    }
    assert owners == {
        format_id: "src/sceneio/io/_inspectors/splats.py"
        for format_id in SPLAT_IDS
    }


@pytest.mark.parametrize("format_id", SPLAT_IDS)
def test_splat_valid_artifacts_match_exact_parent(
    tmp_path,
    format_id,
):
    path = _write_valid(tmp_path)[format_id]
    expected = CONTRACT["valid"][format_id]
    payload = path.read_bytes()
    assert len(payload) == expected["byte_size"]
    if format_id == "sog":
        _assert_sog_archive(payload)
    else:
        assert hashlib.sha256(payload).hexdigest() == expected["sha256"]
    info = sceneio.inspect(path, format=format_id)
    lower_info = getattr(
        splat_inspector,
        INSPECTOR_NAMES[format_id],
    )(path, registry.REGISTRY[format_id].datatype)
    decoded = sceneio.read(path, format=format_id)
    assert _normalized_inspection(info) == expected["inspection"]
    assert _normalized_inspection(lower_info) == expected["inspection"]
    record_contract = {
        "ksplat": "ksplat",
        "spz": "spz_v3_v4",
        "splat": "splat",
    }.get(format_id)
    if record_contract is None:
        assert _record_fingerprint(decoded) == expected["record_sha256"]
    else:
        _assert_portable_record(decoded, record_contract)

    released = path.with_suffix(path.suffix + ".released")
    path.rename(released)
    released.unlink()
    assert _normalized_inspection(info) == expected["inspection"]
    assert _normalized_inspection(lower_info) == expected["inspection"]
    if record_contract is None:
        assert _record_fingerprint(decoded) == expected["record_sha256"]
    else:
        _assert_portable_record(decoded, record_contract)


def test_splat_family_uniform_public_path_and_path_release(tmp_path):
    cloud = _cloud()
    retained = []
    for format_id in SPLAT_IDS:
        path = tmp_path / f"registry{SUFFIXES[format_id]}"
        sceneio.write(cloud, path, format=format_id)
        assert sceneio.detect(path) == format_id

        info = sceneio.inspect(path, format=format_id)
        decoded = sceneio.read(path, format=format_id)
        explicit = sceneio.read(path, format=format_id)
        assert info.format == format_id
        assert info.datatype == "splat"
        assert info.count == cloud.num_gaussians
        assert _record_fingerprint(decoded) == _record_fingerprint(explicit)

        selected = None
        if format_id in PARTIAL_IDS:
            selected = sceneio.read_partial(
                path,
                format=format_id,
                points=(2, 6),
            )
            _assert_cloud_slice(selected, decoded, 2, 6)
        else:
            assert sceneio.capabilities(format_id).partial_selectors == ()

        released = path.with_suffix(path.suffix + ".released")
        path.rename(released)
        released.unlink()
        retained.append((format_id, info, decoded, explicit, selected))

    assert len(retained) == len(SPLAT_IDS)
    for format_id, info, decoded, explicit, selected in retained:
        assert info.format == format_id
        assert decoded.num_gaussians == cloud.num_gaussians
        assert _record_fingerprint(decoded) == _record_fingerprint(explicit)
        if selected is not None:
            _assert_cloud_slice(selected, decoded, 2, 6)


def test_sog_directory_artifact_matches_exact_parent(tmp_path):
    path = tmp_path / "valid_sog_directory"
    sceneio.write(_cloud(), path, format="sog")
    expected = CONTRACT["valid"]["sog_directory"]
    files = {
        value.relative_to(path).as_posix(): {
            "byte_size": value.stat().st_size,
            "sha256": hashlib.sha256(value.read_bytes()).hexdigest(),
        }
        for value in sorted(path.rglob("*"))
        if value.is_file()
    }
    assert set(files) == set(expected["files"])
    for name, descriptor in files.items():
        assert descriptor["byte_size"] == expected["files"][name][
            "byte_size"
        ]
        if name != "meta.json":
            assert descriptor["sha256"] == expected["files"][name][
                "sha256"
            ]
    metadata = (path / "meta.json").read_bytes()
    metadata_sha256, means_min_z_hex = _assert_sog_metadata(metadata)
    assert files["meta.json"]["sha256"] == metadata_sha256
    _assert_sog_profile(
        archive_sha256=None,
        metadata_sha256=metadata_sha256,
        means_min_z_hex=means_min_z_hex,
    )
    directory_info = sceneio.inspect(path, format="sog")
    metadata_info = sceneio.inspect(path / "meta.json", format="sog")
    lower_directory_info = splat_inspector.inspect_sog(path, "splat")
    lower_metadata_info = splat_inspector.inspect_sog(
        path / "meta.json",
        "splat",
    )
    directory_record = sceneio.read(path, format="sog")
    metadata_record = sceneio.read(path / "meta.json", format="sog")
    assert _normalized_inspection(directory_info) == expected["inspection"]
    assert _normalized_inspection(metadata_info) == expected["inspection"]
    assert _normalized_inspection(lower_directory_info) == expected[
        "inspection"
    ]
    assert _normalized_inspection(lower_metadata_info) == expected[
        "inspection"
    ]
    assert _record_fingerprint(directory_record) == expected["record_sha256"]
    assert _record_fingerprint(metadata_record) == expected["record_sha256"]

    shutil.rmtree(path)
    assert _normalized_inspection(directory_info) == expected["inspection"]
    assert _normalized_inspection(metadata_info) == expected["inspection"]
    assert _normalized_inspection(lower_directory_info) == expected[
        "inspection"
    ]
    assert _normalized_inspection(lower_metadata_info) == expected[
        "inspection"
    ]
    assert _record_fingerprint(directory_record) == expected["record_sha256"]
    assert _record_fingerprint(metadata_record) == expected["record_sha256"]


def test_sog_retained_inspections_release_layers_and_directory(tmp_path):
    path = tmp_path / "retained_sog"
    sceneio.write(_cloud(), path, format="sog")
    metadata_path = path / "meta.json"
    directory_info = sceneio.inspect(path, format="sog")
    metadata_info = sceneio.inspect(metadata_path, format="sog")
    layers = sorted(
        item for item in path.iterdir() if item.name != "meta.json"
    )
    assert layers

    for layer in layers:
        moved = layer.with_name(layer.name + ".moved")
        layer.rename(moved)
        moved.rename(layer)

    retired = path.with_name(path.name + ".retired")
    path.rename(retired)
    path.mkdir()
    shutil.rmtree(path)
    shutil.rmtree(retired)
    assert directory_info.metadata["packaging"] == "directory"
    assert metadata_info.metadata["packaging"] == "directory"


@pytest.mark.parametrize("entry_kind", ["directory", "metadata"])
def test_sog_retained_missing_layer_exception_releases_directory(
    tmp_path,
    entry_kind,
):
    path = tmp_path / f"missing_layer_{entry_kind}"
    sceneio.write(_cloud(), path, format="sog")
    missing = next(
        item for item in path.iterdir() if item.name != "meta.json"
    )
    missing_name = missing.name
    missing.unlink()
    entry = path if entry_kind == "directory" else path / "meta.json"

    with pytest.raises(sceneio.FormatError) as captured:
        sceneio.inspect(entry, format="sog")
    assert "missing declared layer" in str(captured.value.__cause__)
    assert missing_name in str(captured.value.__cause__)

    retired = path.with_name(path.name + ".retired")
    path.rename(retired)
    path.mkdir()
    shutil.rmtree(path)
    shutil.rmtree(retired)
    assert missing_name in str(captured.value.__cause__)


@pytest.mark.parametrize("version", [1, 2])
def test_spz_legacy_artifacts_match_exact_parent(tmp_path, version):
    expected = CONTRACT["valid"][f"spz_v{version}"]
    payload = base64.b64decode(expected["base64"])
    assert len(payload) == expected["byte_size"]
    assert hashlib.sha256(payload).hexdigest() == expected["sha256"]

    path = tmp_path / f"valid_v{version}.spz"
    path.write_bytes(payload)
    assert sceneio.detect(path) == "spz"
    assert _normalized_inspection(
        sceneio.inspect(path, format="spz")
    ) == expected["inspection"]
    assert _record_fingerprint(
        sceneio.read(path, format="spz")
    ) == expected["record_sha256"]

    extensionless = tmp_path / f"extensionless_spz_v{version}"
    extensionless.write_bytes(payload)
    assert sceneio.detect(extensionless) == "spz"
    assert _record_fingerprint(
        sceneio.read(extensionless)
    ) == expected["record_sha256"]


def test_spz_v4_artifact_matches_exact_parent(tmp_path):
    path = tmp_path / "valid_v4.spz"
    path.write_bytes(bytes(_core.write_spz(_cloud(), version=4)))
    expected = CONTRACT["valid"]["spz_v4"]
    payload = path.read_bytes()
    assert len(payload) == expected["byte_size"]
    assert hashlib.sha256(payload).hexdigest() == expected["sha256"]
    assert _normalized_inspection(
        sceneio.inspect(path, format="spz")
    ) == expected["inspection"]
    _assert_portable_record(
        sceneio.read(path, format="spz"),
        "spz_v3_v4",
    )


@pytest.mark.parametrize("format_id", SPLAT_IDS)
def test_splat_invalid_inspection_matches_exact_parent(
    tmp_path,
    format_id,
):
    path = tmp_path / f"bad{SUFFIXES[format_id]}"
    path.write_bytes(b"bad")
    expected = CONTRACT["malformed"][format_id]
    with pytest.raises(sceneio.FormatError) as captured:
        sceneio.inspect(path, format=format_id)
    cause = captured.value.__cause__
    assert type(cause).__name__ == expected["cause_type"]
    assert str(cause) == expected["cause_message"]
    path.unlink()
    assert str(captured.value.__cause__) == expected["cause_message"]


@pytest.mark.parametrize("format_id", PARTIAL_IDS)
def test_splat_point_ranges_match_full_records(tmp_path, format_id):
    path = _write_valid(tmp_path)[format_id]
    full = sceneio.read(path, format=format_id)
    selected = sceneio.read_partial(
        path,
        format=format_id,
        points=(2, 6),
    )
    _assert_cloud_slice(selected, full, 2, 6)
    released = path.with_suffix(path.suffix + ".released")
    path.rename(released)
    released.unlink()
    _assert_cloud_slice(selected, full, 2, 6)


def test_sog_directory_and_metadata_point_ranges_match(tmp_path):
    path = tmp_path / "sog_directory"
    sceneio.write(_cloud(), path, format="sog")
    full = sceneio.read(path, format="sog")
    selected_records = []
    for entry in (path, path / "meta.json"):
        selected = sceneio.read_partial(
            entry,
            format="sog",
            points=(2, 6),
        )
        _assert_cloud_slice(selected, full, 2, 6)
        selected_records.append(selected)
    shutil.rmtree(path)
    for selected in selected_records:
        _assert_cloud_slice(selected, full, 2, 6)


def test_spz_deliberately_has_no_point_selector(tmp_path):
    path = _write_valid(tmp_path)["spz"]
    assert sceneio.capabilities("spz").partial_selectors == ()
    with pytest.raises(sceneio.FormatError, match="point-subset reads"):
        sceneio.read_partial(path, format="spz", points=(0, 1))


def test_ply_and_spz_detection_precedence_is_parent_exact(tmp_path):
    paths = _write_valid(tmp_path)
    assert sceneio.detect(paths["gaussian_ply"]) == "gaussian_ply"
    assert sceneio.detect(paths["compressed_ply"]) == "compressed_ply"
    for format_id in ("gaussian_ply", "compressed_ply"):
        extensionless = tmp_path / f"extensionless_{format_id}"
        shutil.copyfile(paths[format_id], extensionless)
        assert sceneio.detect(extensionless) == format_id

    point_path = tmp_path / "point.ply"
    point_path.write_bytes(
        bytes(
            _core.write_ply(
                _core.point_cloud(
                    np.array(
                        [[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]],
                        dtype=np.float32,
                    )
                )
            )
        )
    )
    assert sceneio.detect(point_path) == "ply"
    point_extensionless = tmp_path / "extensionless_point_ply"
    shutil.copyfile(point_path, point_extensionless)
    assert sceneio.detect(point_extensionless) == "ply"

    mesh_path = tmp_path / "mesh.ply"
    mesh_path.write_bytes(
        bytes(
            _core.write_ply_mesh(
                _core.mesh(
                    np.array(
                        [
                            [0.0, 0.0, 0.0],
                            [1.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0],
                        ],
                        dtype=np.float32,
                    ),
                    np.array([0, 3], dtype=np.uint64),
                    np.array([0, 1, 2], dtype=np.uint64),
                )
            )
        )
    )
    assert sceneio.detect(mesh_path) == "ply_mesh"
    mesh_extensionless = tmp_path / "extensionless_mesh_ply"
    shutil.copyfile(mesh_path, mesh_extensionless)
    assert sceneio.detect(mesh_extensionless) == "ply_mesh"

    assert sceneio.detect(paths["sog"]) == "sog"
    assert sceneio.detect(paths["ksplat"]) == "ksplat"
    assert sceneio.detect(paths["splat"]) == "splat"
    sog_directory = tmp_path / "detect_sog_directory"
    sceneio.write(_cloud(), sog_directory, format="sog")
    assert sceneio.detect(sog_directory) == "sog"
    assert sceneio.detect(sog_directory / "meta.json") == "sog"

    spz_v3 = tmp_path / "extensionless_spz_v3"
    shutil.copyfile(paths["spz"], spz_v3)
    assert sceneio.detect(spz_v3) == "spz"
    spz_v4 = tmp_path / "extensionless_spz_v4"
    spz_v4.write_bytes(bytes(_core.write_spz(_cloud(), version=4)))
    assert sceneio.detect(spz_v4) == "spz"


def test_sog_explicit_format_routing_is_suffix_agnostic(tmp_path):
    archive = tmp_path / "source.sog"
    sceneio.write(_cloud(), archive, format="sog")
    expected = _record_fingerprint(sceneio.read(archive, format="sog"))

    for name in ("suffixless_archive", "alternate.bin"):
        candidate = tmp_path / name
        shutil.copyfile(archive, candidate)
        assert _record_fingerprint(
            sceneio.read(candidate, format="sog")
        ) == expected

    directory = tmp_path / "suffixless_output"
    sceneio.write(_cloud(), directory, format="sog")
    assert directory.is_dir()
    assert (directory / "meta.json").is_file()

    alternate = tmp_path / "alternate.output"
    sceneio.write(_cloud(), alternate, format="sog")
    assert alternate.is_file()
    assert zipfile.is_zipfile(alternate)

    dotted_directory = tmp_path / "existing.directory"
    dotted_directory.mkdir()
    sceneio.write(_cloud(), dotted_directory, format="sog")
    assert (dotted_directory / "meta.json").is_file()


def _extend_sparse(path: Path, size: int) -> None:
    with path.open("r+b") as stream:
        stream.seek(size - 1)
        stream.write(b"\0")


def _large_splat_inspection_paths(root: Path) -> dict[str, Path]:
    root.mkdir()
    paths = _write_valid(root)
    large_extent = 36 * 1024 * 1024

    _extend_sparse(paths["gaussian_ply"], large_extent)

    compressed = paths["compressed_ply"]
    payload = compressed.read_bytes()
    header_end = payload.index(b"end_header\n") + len(b"end_header\n")
    vertex_count = 2_350_000
    chunk_count = (vertex_count + 255) // 256
    header = payload[:header_end].replace(
        b"element chunk 1\n",
        f"element chunk {chunk_count}\n".encode(),
    ).replace(
        b"element vertex 8\n",
        f"element vertex {vertex_count}\n".encode(),
    )
    compressed.write_bytes(header)
    _extend_sparse(
        compressed,
        len(header) + chunk_count * 72 + vertex_count * 16,
    )

    sog = root / "large_sog"
    sceneio.write(_cloud(), sog, format="sog")
    _extend_sparse(sog / "means_l.webp", large_extent)

    ksplat = paths["ksplat"]
    point_count = 870_000
    record_bytes = point_count * 44
    header = bytearray(4096 + 1024)
    header[0] = 0
    header[1] = 1
    struct.pack_into(
        "<IIIIH",
        header,
        4,
        1,
        1,
        point_count,
        point_count,
        0,
    )
    struct.pack_into(
        "<II",
        header,
        4096,
        point_count,
        point_count,
    )
    struct.pack_into("<I", header, 4096 + 28, record_bytes)
    struct.pack_into("<H", header, 4096 + 40, 0)
    ksplat.write_bytes(header)
    _extend_sparse(ksplat, len(header) + record_bytes)

    spz = root / "large.spz"
    spz.write_bytes(bytes(_core.write_spz(_cloud(), version=4))[:32])
    _extend_sparse(spz, large_extent)

    _extend_sparse(paths["splat"], large_extent)
    return {
        "gaussian_ply": paths["gaussian_ply"],
        "compressed_ply": compressed,
        "sog": sog,
        "ksplat": ksplat,
        "spz": spz,
        "splat": paths["splat"],
    }


def test_large_splat_inspection_is_bounded_and_releases_paths(tmp_path):
    minimum_size = 36 * 1024 * 1024
    for format_id, path in _large_splat_inspection_paths(
        tmp_path / "large"
    ).items():
        size = (
            sum(item.stat().st_size for item in path.iterdir())
            if path.is_dir()
            else path.stat().st_size
        )
        assert size >= minimum_size
        gc.collect()
        tracemalloc.start()
        try:
            info = sceneio.inspect(path, format=format_id)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert peak < 2 * 1024 * 1024, (format_id, peak)

        released = path.with_name(path.name + ".released")
        path.rename(released)
        if released.is_dir():
            shutil.rmtree(released)
        else:
            released.unlink()
        assert info.format == format_id


def test_oracle_independent_gaussian_ply_invalid_matrix(tmp_path):
    truncated = tmp_path / "truncated.ply"
    truncated.write_bytes(b"ply\nformat binary_little_endian 1.0\n")
    with pytest.raises(sceneio.FormatError, match="missing end_header"):
        sceneio.inspect(truncated, format="gaussian_ply")

    malformed = tmp_path / "malformed.ply"
    malformed.write_bytes(
        b"ply\n"
        b"format binary_little_endian 1.0\n"
        b"element vertex 1\n"
        b"property double x\n"
        b"end_header\n"
    )
    with pytest.raises(
        sceneio.FormatError,
        match="only float32 vertex properties are supported",
    ):
        sceneio.inspect(malformed, format="gaussian_ply")

    declared = tmp_path / "declared_extent.ply"
    payload = bytes(_core.write_gaussian_ply(_cloud()))
    declared.write_bytes(payload[:-1])
    assert sceneio.inspect(declared, format="gaussian_ply").count == 8
    with pytest.raises(sceneio.FormatError):
        sceneio.read(declared, format="gaussian_ply")


def test_oracle_independent_spz_invalid_matrix(tmp_path):
    raw_truncated = tmp_path / "raw_truncated.spz"
    raw_truncated.write_bytes(b"NGSP")
    with pytest.raises(sceneio.FormatError, match="truncated v4 header"):
        sceneio.inspect(raw_truncated, format="spz")

    gzip_truncated = tmp_path / "gzip_truncated.spz"
    gzip_truncated.write_bytes(gzip.compress(b"NGSP"))
    with pytest.raises(sceneio.FormatError, match="truncated legacy SPZ header"):
        sceneio.inspect(gzip_truncated, format="spz")

    valid = bytearray(_core.write_spz(_cloud(), version=4))
    mutations = (
        ("version", 4, struct.pack("<I", 5), "bad v4 header"),
        ("degree", 12, b"\x04", "unsupported SH degree"),
        ("fractional_bits", 13, b"\x00", "invalid fractional_bits"),
    )
    for name, offset, replacement, message in mutations:
        damaged = bytearray(valid)
        damaged[offset : offset + len(replacement)] = replacement
        path = tmp_path / f"{name}.spz"
        path.write_bytes(damaged)
        with pytest.raises(sceneio.FormatError, match=message):
            sceneio.inspect(path, format="spz")

    declared = bytearray(valid)
    declared[8:12] = struct.pack("<I", 1_000_000)
    declared_path = tmp_path / "declared_count.spz"
    declared_path.write_bytes(declared)
    assert sceneio.inspect(declared_path, format="spz").count == 1_000_000
    with pytest.raises(sceneio.FormatError):
        sceneio.read(declared_path, format="spz")


def test_oracle_independent_splat_invalid_extent(tmp_path):
    path = tmp_path / "invalid.splat"
    path.write_bytes(b"\0" * 31)
    with pytest.raises(sceneio.FormatError, match="multiple of 32"):
        sceneio.inspect(path, format="splat")
    with pytest.raises(sceneio.FormatError):
        sceneio.read(path, format="splat")
