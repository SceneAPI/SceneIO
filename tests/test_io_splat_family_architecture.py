"""Architecture and exact-parent behavior contracts for the splat family."""

from __future__ import annotations

import ast
import base64
import copy
import gzip
import hashlib
import inspect
import json
import shutil
import struct
import zipfile
from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import _core
from sceneio.io import registry
from sceneio.io._builtin_manifest import (
    CANONICAL_BUILTIN_IDS,
    FAMILY_MEMBERS,
)

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
        fields.append(
            [
                name,
                str(value.dtype),
                list(value.shape),
                hashlib.sha256(value.tobytes()).hexdigest(),
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


@pytest.mark.parametrize("format_id", SPLAT_IDS)
def test_splat_valid_artifacts_match_exact_parent(
    tmp_path,
    format_id,
):
    path = _write_valid(tmp_path)[format_id]
    expected = CONTRACT["valid"][format_id]
    payload = path.read_bytes()
    assert len(payload) == expected["byte_size"]
    assert hashlib.sha256(payload).hexdigest() == expected["sha256"]
    info = sceneio.inspect(path, format=format_id)
    decoded = sceneio.read(path, format=format_id)
    assert _normalized_inspection(info) == expected["inspection"]
    assert _record_fingerprint(decoded) == expected["record_sha256"]

    released = path.with_suffix(path.suffix + ".released")
    path.rename(released)
    released.unlink()
    assert _normalized_inspection(info) == expected["inspection"]
    assert _record_fingerprint(decoded) == expected["record_sha256"]


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
    assert files == expected["files"]
    directory_info = sceneio.inspect(path, format="sog")
    metadata_info = sceneio.inspect(path / "meta.json", format="sog")
    directory_record = sceneio.read(path, format="sog")
    metadata_record = sceneio.read(path / "meta.json", format="sog")
    assert _normalized_inspection(directory_info) == expected["inspection"]
    assert _normalized_inspection(metadata_info) == expected["inspection"]
    assert _record_fingerprint(directory_record) == expected["record_sha256"]
    assert _record_fingerprint(metadata_record) == expected["record_sha256"]

    shutil.rmtree(path)
    assert _normalized_inspection(directory_info) == expected["inspection"]
    assert _normalized_inspection(metadata_info) == expected["inspection"]
    assert _record_fingerprint(directory_record) == expected["record_sha256"]
    assert _record_fingerprint(metadata_record) == expected["record_sha256"]


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
    assert _record_fingerprint(
        sceneio.read(path, format="spz")
    ) == expected["record_sha256"]


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
