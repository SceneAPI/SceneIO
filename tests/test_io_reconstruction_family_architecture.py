"""Architecture and parent-behavior contracts for reconstruction inspectors."""

from __future__ import annotations

import ast
import dataclasses
import gc
import hashlib
import importlib
import inspect
import json
import sqlite3
import subprocess
import sys
import textwrap
import tomllib
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

import sceneio
from bench import bench_io
from sceneio import _core
from sceneio.io import _inspection, registry
from sceneio.io._builtin_manifest import (
    CANONICAL_BUILTIN_IDS,
    FAMILY_MEMBERS,
)
from sceneio.io._inspectors import reconstruction as reconstruction_inspector
from sceneio.io._registry.families import (
    reconstruction as reconstruction_family,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "tests" / "contracts" / "io_reconstruction_family_v1.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
RECONSTRUCTION_IDS = FAMILY_MEMBERS["reconstruction"]

_INSPECTOR_NAMES = {
    "colmap_sparse": "inspect_colmap_binary",
    "transforms_json": "inspect_transforms",
    "tum": "inspect_pose_text",
    "kitti": "inspect_pose_text",
    "euroc_state": "inspect_euroc_state",
    "g2o": "inspect_g2o",
    "colmap_db": "inspect_colmap_db",
    "colmap_sparse_txt": "inspect_colmap_text",
    "bundler": "inspect_bundler",
    "bal": "inspect_bal",
    "nvm": "inspect_nvm",
    "openmvg": "inspect_openmvg",
}
_CORE_READ_NAMES = {
    format_id: (
        "read_colmap_txt"
        if format_id == "colmap_sparse_txt"
        else f"read_{format_id}"
    )
    for format_id in RECONSTRUCTION_IDS
}


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


def _array(value) -> dict[str, object] | None:
    if value is None:
        return None
    array = np.asarray(value)
    return {
        "dtype": array.dtype.str,
        "shape": list(array.shape),
        "sha256": hashlib.sha256(array.tobytes()).hexdigest(),
    }


def _arrays(value, names: tuple[str, ...]) -> dict[str, object]:
    return {name: _array(getattr(value, name)) for name in names}


def _camera(value) -> dict[str, object]:
    return {
        "id": int(value.id),
        "model_id": int(value.model_id),
        "model": value.model,
        "width": int(value.width),
        "height": int(value.height),
        "params": _array(value.params),
    }


def _feature(value) -> dict[str, object]:
    return {
        "image_id": int(value.image_id),
        "image_name": value.image_name,
        "camera_id": int(value.camera_id),
        "image_size": list(value.image_size),
        "extractor_type": int(value.extractor_type),
        "time_id": None if value.time_id is None else int(value.time_id),
        "descriptor_dtype": value.descriptor_dtype,
        "descriptor_dim": value.descriptor_dim,
        "descriptor_dtype_present": bool(value.descriptor_dtype_present),
        "descriptor_dim_present": bool(value.descriptor_dim_present),
        "extractor_type_name": value.extractor_type_name,
        "keypoints_present": bool(value.keypoints_present),
        "quality": value.quality,
        "arrays": _arrays(
            value,
            ("keypoints", "descriptors", "keypoint_colors", "scores"),
        ),
    }


def _record(value) -> dict[str, object]:
    name = type(value).__name__
    if name == "Reconstruction":
        return {
            "type": name,
            "cameras": [_camera(camera) for camera in value.cameras],
            "image_names": list(value.image_names),
            "arrays": _arrays(
                value,
                (
                    "image_ids",
                    "image_camera_ids",
                    "quaternions",
                    "translations",
                    "point3D_ids",
                    "xyz",
                    "rgb",
                    "errors",
                ),
            ),
            "quaternion_order": value.quaternion_order,
            "pose_convention": value.pose_convention,
        }
    if name == "PosedViewSet":
        return {
            "type": name,
            "cameras": [_camera(camera) for camera in value.cameras],
            "names": list(value.names),
            "arrays": _arrays(
                value,
                (
                    "quaternions",
                    "translations",
                    "camera_indices",
                    "timestamps",
                ),
            ),
            "quaternion_order": value.quaternion_order,
            "pose_convention": value.pose_convention,
            "axis_frame": value.axis_frame,
            "scale_to_meters": float(value.scale_to_meters),
        }
    if name == "StateTrajectory":
        return {
            "type": name,
            "arrays": _arrays(
                value,
                (
                    "timestamps_ns",
                    "positions",
                    "quaternions",
                    "velocities",
                    "gyro_biases",
                    "accel_biases",
                ),
            ),
            "metadata": {
                key: getattr(value, key)
                for key in (
                    "timestamp_unit",
                    "quaternion_order",
                    "quaternion_sign",
                    "pose_convention",
                    "position_frame",
                    "velocity_frame",
                    "bias_frame",
                    "position_unit",
                    "velocity_unit",
                    "gyro_bias_unit",
                    "accel_bias_unit",
                )
            },
        }
    if name == "PoseGraph":
        return {
            "type": name,
            "arrays": _arrays(
                value,
                (
                    "node_ids",
                    "node_translations",
                    "node_quaternions",
                    "fixed",
                    "edge_endpoints",
                    "edge_translations",
                    "edge_quaternions",
                    "information_matrices",
                ),
            ),
            "node_types": list(value.node_types),
            "edge_types": list(value.edge_types),
            "metadata": {
                key: getattr(value, key)
                for key in (
                    "quaternion_order",
                    "quaternion_sign",
                    "node_transform_convention",
                    "edge_transform_convention",
                    "translation_unit",
                    "information_variable_order",
                    "information_storage",
                )
            },
        }
    if name == "ColmapDatabase":
        image_ids = [int(image_id) for image_id in np.asarray(value.image_ids)]
        match_graph = value.match_graph
        return {
            "type": name,
            "profile": value.profile,
            "application_id": int(value.application_id),
            "user_version": int(value.user_version),
            "cameras": [_camera(camera) for camera in value.cameras],
            "image_ids": image_ids,
            "prior_focal_length": _array(value.prior_focal_length),
            "features": [
                _feature(value.feature(image_id)) for image_id in image_ids
            ],
            "match_graph": {
                "arrays": _arrays(
                    match_graph,
                    (
                        "image_pairs",
                        "pair_ids",
                        "match_offsets",
                        "matches",
                        "scores",
                        "match_score_present",
                        "verified_offsets",
                        "verified_matches",
                        "configs",
                        "fundamental_matrices",
                        "essential_matrices",
                        "homographies",
                        "qvecs",
                        "tvecs",
                        "match_present",
                        "geometry_present",
                        "F_present",
                        "E_present",
                        "H_present",
                        "pose_present",
                        "provenance_present",
                        "source_flags",
                        "retrieval_score_present",
                        "retrieval_scores",
                    ),
                ),
                "quaternion_order": match_graph.quaternion_order,
                "relative_pose_convention": match_graph.relative_pose_convention,
            },
            "pose_priors": {
                "generalized": bool(value.pose_priors.generalized),
                "arrays": _arrays(
                    value.pose_priors,
                    (
                        "prior_ids",
                        "correlated_data_ids",
                        "correlated_sensor_ids",
                        "correlated_sensor_types",
                        "coordinate_systems",
                        "position_present",
                        "positions",
                        "position_covariance_present",
                        "position_covariances",
                        "gravity_present",
                        "gravities",
                        "rotation_present",
                        "rotations",
                        "rotation_covariance_present",
                        "rotation_covariances",
                        "pose_covariance_present",
                        "pose_covariances",
                    ),
                ),
                "rotation_order": value.pose_priors.rotation_order,
                "rotation_convention": value.pose_priors.rotation_convention,
                "covariance_storage": value.pose_priors.covariance_storage,
                "rotation_covariance_variable_order": (
                    value.pose_priors.rotation_covariance_variable_order
                ),
                "pose_covariance_variable_order": (
                    value.pose_priors.pose_covariance_variable_order
                ),
                "rotation_covariance_unit": (
                    value.pose_priors.rotation_covariance_unit
                ),
                "position_covariance_unit": (
                    value.pose_priors.position_covariance_unit
                ),
                "pose_covariance_cross_unit": (
                    value.pose_priors.pose_covariance_cross_unit
                ),
            },
            "markers": {
                "arrays": _arrays(
                    value.markers,
                    (
                        "marker_ids",
                        "marker_types",
                        "world_position_present",
                        "world_positions",
                        "world_position_covariance_present",
                        "world_position_covariances",
                        "point3D_ids",
                        "enabled",
                        "projection_marker_ids",
                        "projection_image_ids",
                        "projection_xy",
                        "projection_sizes",
                        "projection_pinned",
                        "projection_point2D_indices",
                    ),
                ),
                "labels": list(value.markers.labels),
                "projection_coordinate_origin": (
                    value.markers.projection_coordinate_origin
                ),
                "projection_coordinate_unit": (
                    value.markers.projection_coordinate_unit
                ),
                "projection_size_unit": value.markers.projection_size_unit,
            },
            "video_metadata": {
                "arrays": _arrays(
                    value.video_metadata,
                    (
                        "video_ids",
                        "source_path_present",
                        "content_hash_present",
                        "widths",
                        "heights",
                        "num_frames",
                        "fps",
                        "duration_seconds",
                        "codec_name_present",
                        "sync_group_present",
                        "frame_video_ids",
                        "frame_image_ids",
                        "video_frame_indices",
                        "pts_present",
                        "pts_seconds",
                        "time_id_present",
                        "time_ids",
                    ),
                ),
                "names": list(value.video_metadata.names),
                "source_paths": list(value.video_metadata.source_paths),
                "content_hashes": list(value.video_metadata.content_hashes),
                "codec_names": list(value.video_metadata.codec_names),
                "sync_groups": list(value.video_metadata.sync_groups),
            },
            "maxx_schema_info": (
                None
                if value.maxx_schema_info is None
                else {
                    "schema_version": value.maxx_schema_info.schema_version,
                    "minimum_reader_version": (
                        value.maxx_schema_info.minimum_reader_version
                    ),
                    "producer_version": value.maxx_schema_info.producer_version,
                    "producer_commit": value.maxx_schema_info.producer_commit,
                }
            ),
        }
    raise TypeError(name)


def _database_record():
    camera = _core.camera(
        5,
        1,
        640,
        480,
        np.array([500.0, 501.0, 320.0, 240.0]),
    )
    features = [
        _core.feature_set(
            np.array([[10.0, 20.0], [30.0, 40.0]], np.float32),
            np.arange(8, dtype=np.uint8).reshape(2, 4) + image_id,
            image_id=image_id,
            image_name=f"{image_id}.jpg",
            camera_id=5,
            image_size=(640, 480),
            extractor_type=0,
        )
        for image_id in (2, 11)
    ]
    graph = _core.match_graph(
        np.array([[2, 11]], np.uint32),
        np.array([0, 1], np.uint64),
        np.array([[0, 1]], np.uint32),
        np.array([0, 1], np.uint64),
        np.array([[0, 1]], np.uint32),
        configs=np.array([2], np.int32),
        fundamental_matrices=np.eye(3)[None],
        fundamental_present=np.array([1], np.uint8),
        geometry_present=np.array([1], np.uint8),
        match_present=np.array([1], np.uint8),
    )
    return _core.colmap_database(
        [camera],
        features,
        graph,
        prior_focal_length=np.array([1], np.uint8),
    )


def _records() -> dict[str, object]:
    reconstruction, transforms, tum, kitti = bench_io._poses_and_reconstruction(
        0.0001
    )
    euroc, _ = bench_io._euroc_fixture(0.00001)
    graph, _ = bench_io._g2o_fixture(0.00008)
    bal, _ = bench_io._bal_fixture(0.0001)
    return {
        "colmap_sparse": reconstruction,
        "transforms_json": transforms,
        "tum": tum,
        "kitti": kitti,
        "euroc_state": euroc,
        "g2o": graph,
        "colmap_db": _database_record(),
        "colmap_sparse_txt": reconstruction,
        "bundler": reconstruction,
        "bal": bal,
        "nvm": reconstruction,
        "openmvg": reconstruction,
    }


def _paths(root: Path) -> dict[str, Path]:
    return {
        "colmap_sparse": root / "colmap-binary",
        "transforms_json": root / "transforms.json",
        "tum": root / "poses.tum",
        "kitti": root / "poses.kitti",
        "euroc_state": root / "states.csv",
        "g2o": root / "graph.g2o",
        "colmap_db": root / "database.db",
        "colmap_sparse_txt": root / "colmap-text",
        "bundler": root / "bundle.out",
        "bal": root / "problem.bal",
        "nvm": root / "model.nvm",
        "openmvg": root / "sfm_data.json",
    }


def _write_valid(
    root: Path,
    format_ids: tuple[str, ...] = RECONSTRUCTION_IDS,
) -> dict[str, Path]:
    root.mkdir()
    paths = {
        format_id: path
        for format_id, path in _paths(root).items()
        if format_id in format_ids
    }
    records = _records()
    for format_id, path in paths.items():
        if registry.REGISTRY[format_id].is_directory:
            path.mkdir()
        sceneio.write(records[format_id], path, format=format_id)
    return paths


def _artifact(path: Path) -> dict[str, object]:
    if path.is_dir():
        return {
            "kind": "directory",
            "members": {
                item.name: {
                    "byte_size": item.stat().st_size,
                    "sha256": hashlib.sha256(item.read_bytes()).hexdigest(),
                }
                for item in sorted(path.iterdir(), key=lambda value: value.name)
                if item.is_file()
            },
        }
    return {
        "kind": "file",
        "byte_size": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


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


def _lower_inspect(format_id: str, path: Path):
    inspector = getattr(reconstruction_inspector, _INSPECTOR_NAMES[format_id])
    datatype = registry.REGISTRY[format_id].datatype
    if format_id in {"tum", "kitti"}:
        return inspector(path, format_id, datatype)
    return inspector(path, datatype)


def _malformed_path(root: Path, format_id: str) -> Path:
    path = root / format_id
    if format_id == "colmap_sparse":
        path.mkdir()
        (path / "cameras.bin").write_bytes(b"bad")
        (path / "images.bin").write_bytes(b"")
        (path / "points3D.bin").write_bytes(b"")
    elif format_id == "colmap_sparse_txt":
        path.mkdir()
        (path / "cameras.txt").write_bytes(b"# incomplete model\n")
    else:
        path.write_bytes(b"bad")
    return path


def _normalized_message(error: BaseException, path: Path) -> str:
    return str(error).replace(str(path), "{path}")


def _remove_path(path: Path) -> None:
    if path.is_dir():
        for child in path.iterdir():
            if child.is_file():
                child.unlink()
        path.rmdir()
    else:
        path.unlink()


def _operation_descriptor(value) -> dict[str, object] | None:
    if value is None:
        return None
    descriptor: dict[str, object] = {
        "module": value.__module__,
        "name": value.__name__,
    }
    closure = inspect.getclosurevars(value).nonlocals if inspect.isfunction(value) else {}
    if closure:
        descriptor["closure"] = {
            name: (
                None
                if target is None
                else f"{target.__module__}.{target.__name__}"
            )
            for name, target in closure.items()
        }
    return descriptor


def test_reconstruction_definitions_preserve_order_contract_and_identity():
    definitions = registry.RECONSTRUCTION_CODECS
    assert isinstance(definitions, tuple)
    assert definitions is reconstruction_family.RECONSTRUCTION_CODECS
    assert tuple(codec.id for codec in definitions) == RECONSTRUCTION_IDS
    assert tuple(CONTRACT["family_ids"]) == RECONSTRUCTION_IDS
    assert tuple(registry.REGISTRY) == CANONICAL_BUILTIN_IDS
    assert CONTRACT["canonical_positions"] == {
        format_id: CANONICAL_BUILTIN_IDS.index(format_id)
        for format_id in RECONSTRUCTION_IDS
    }

    operation_fields = ("read", "write", "read_image", "read_pair", "read_states")
    for codec in definitions:
        expected = CONTRACT["registry"][codec.id]
        position = CONTRACT["canonical_positions"][codec.id]
        assert registry.REGISTRY[codec.id] is codec
        assert registry.BUILTIN_DEFINITIONS[position] is codec
        assert codec.record.__name__ == expected["record"]
        assert codec.datatype == expected["datatype"]
        assert list(codec.extensions) == expected["extensions"]
        assert [value.hex() for value in codec.magic] == expected["magic_hex"]
        assert list(codec.filenames) == expected["filenames"]
        assert codec.is_directory is expected["is_directory"]
        assert codec.dir_marker == expected["dir_marker"]
        assert codec.lossy is expected["lossy"]
        assert codec.container_kind == expected["container_kind"]
        assert list(codec.supported_features) == expected["supported_features"]
        assert list(codec.unsupported_features) == expected["unsupported_features"]
        assert codec.inspect is None
        assert {
            field: _operation_descriptor(getattr(codec, field))
            for field in operation_fields
        } == expected["operations"]


def test_reconstruction_family_is_staged_once_and_not_defined_inline():
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
        and node.args[0].value == "reconstruction"
    ]
    assert len(staging) == 1
    assert (
        source.count(
            '_define_builtin_family("reconstruction", RECONSTRUCTION_CODECS)'
        )
        == 1
    )
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Codec"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            assert node.args[0].value not in RECONSTRUCTION_IDS


def test_reconstruction_family_module_is_lower_layer_only():
    source = inspect.getsource(reconstruction_family)
    imports = _absolute_imports(source)
    assert {module for module, _ in imports} <= {
        "__future__",
        "sceneio",
        "sceneio.io._registry.adapters",
        "sceneio.io._registry.model",
    }
    for forbidden in (
        "sceneio.io.registry",
        "sceneio.io._inspection",
        "sceneio.io._registry.assembly",
        "REGISTRY",
        "register(",
    ):
        assert forbidden not in source


def test_reconstruction_family_reload_is_inert_and_registry_reload_is_exact():
    code = textwrap.dedent(
        """
        import importlib

        from sceneio.io import registry
        from sceneio.io._builtin_manifest import (
            CANONICAL_BUILTIN_IDS,
            FAMILY_MEMBERS,
        )
        from sceneio.io._registry.families import reconstruction

        before_registry = registry.REGISTRY
        before_items = tuple(registry.REGISTRY.items())
        before_codecs = registry.RECONSTRUCTION_CODECS
        reloaded_family = importlib.reload(reconstruction)
        assert registry.REGISTRY is before_registry
        assert tuple(registry.REGISTRY.items()) == before_items
        assert registry.RECONSTRUCTION_CODECS is before_codecs
        assert tuple(codec.id for codec in reloaded_family.RECONSTRUCTION_CODECS) == (
            FAMILY_MEMBERS["reconstruction"]
        )
        assert all(
            registry.REGISTRY[codec.id] is not codec
            for codec in reloaded_family.RECONSTRUCTION_CODECS
        )

        for _ in range(2):
            reloaded_registry = importlib.reload(registry)
            assert tuple(reloaded_registry.REGISTRY) == CANONICAL_BUILTIN_IDS
            assert tuple(
                codec.id for codec in reloaded_registry.RECONSTRUCTION_CODECS
            ) == FAMILY_MEMBERS["reconstruction"]
            for codec in reloaded_registry.RECONSTRUCTION_CODECS:
                assert reloaded_registry.REGISTRY[codec.id] is codec
        """
    )
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)


def test_reconstruction_detection_precedence_and_default_writer(tmp_path):
    mixed = tmp_path / "mixed-colmap"
    mixed.mkdir()
    (mixed / "cameras.bin").write_bytes(b"")
    (mixed / "cameras.txt").write_bytes(b"")
    assert sceneio.detect(mixed) == "colmap_sparse"

    default_path = tmp_path / "default-reconstruction"
    default_path.mkdir()
    sceneio.write(_records()["colmap_sparse"], default_path)
    assert sceneio.detect(default_path) == "colmap_sparse"
    assert (default_path / "cameras.bin").is_file()
    assert not (default_path / "cameras.txt").exists()


def test_reconstruction_inspector_module_is_lower_layer_only():
    source = inspect.getsource(reconstruction_inspector)
    imports = _absolute_imports(source)
    assert {module for module, _ in imports} <= {
        "__future__",
        "pathlib",
        "sceneio",
        "sceneio.io._inspectors.common",
        "sceneio.io._inspectors.model",
        "struct",
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
    for format_id in RECONSTRUCTION_IDS:
        assert f"_core.read_{format_id}" not in source
        assert f"_core.write_{format_id}" not in source


def test_reconstruction_inspector_reload_is_inert():
    before_registry = registry.REGISTRY
    before_items = tuple(registry.REGISTRY.items())
    reloaded = importlib.reload(reconstruction_inspector)
    assert reloaded is reconstruction_inspector
    assert registry.REGISTRY is before_registry
    assert tuple(registry.REGISTRY.items()) == before_items


@pytest.mark.parametrize(
    ("wrapper_name", "delegate_name"),
    [
        ("_inspect_colmap_db", "_inspect_reconstruction_colmap_db"),
        ("_inspect_euroc_state", "_inspect_reconstruction_euroc_state"),
        ("_inspect_g2o", "_inspect_reconstruction_g2o"),
        ("_inspect_bundler", "_inspect_reconstruction_bundler"),
        ("_inspect_bal", "_inspect_reconstruction_bal"),
        ("_inspect_nvm", "_inspect_reconstruction_nvm"),
        ("_inspect_transforms", "_inspect_reconstruction_transforms"),
        ("_inspect_openmvg", "_inspect_reconstruction_openmvg"),
        ("_inspect_colmap_binary", "_inspect_reconstruction_colmap_binary"),
        ("_inspect_colmap_text", "_inspect_reconstruction_colmap_text"),
    ],
)
def test_reconstruction_facade_preserves_two_argument_wrappers(
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
    path = Path("reconstruction.fixture")
    wrapper = getattr(_inspection, wrapper_name)
    assert tuple(inspect.signature(wrapper).parameters) == ("path", "datatype")
    assert wrapper(path, "reconstruction") is marker
    assert calls == [(path, "reconstruction")]


def test_pose_text_facade_preserves_three_argument_wrapper(monkeypatch):
    marker = object()
    calls = []

    def inspect_family(path, format_id, datatype):
        calls.append((path, format_id, datatype))
        return marker

    monkeypatch.setattr(
        _inspection,
        "_inspect_reconstruction_pose_text",
        inspect_family,
    )
    path = Path("poses.fixture")
    wrapper = _inspection._inspect_pose_text
    assert tuple(inspect.signature(wrapper).parameters) == (
        "path",
        "format_id",
        "datatype",
    )
    assert wrapper(path, "tum", "posed_views") is marker
    assert calls == [(path, "tum", "posed_views")]


def test_repository_coverage_tracks_all_reconstruction_inspectors():
    coverage = tomllib.loads(
        (
            ROOT / "tests" / "contracts" / "repository_coverage_v1.toml"
        ).read_text(encoding="utf-8")
    )
    owners = {
        item["id"]: item["inspection_source"]
        for item in coverage["codec"]
        if item["id"] in RECONSTRUCTION_IDS
    }
    assert owners == {
        format_id: "src/sceneio/io/_inspectors/reconstruction.py"
        for format_id in RECONSTRUCTION_IDS
    }


def test_reconstruction_inspection_and_reads_match_parent_contract(tmp_path):
    paths = _write_valid(tmp_path / "valid")
    assert tuple(CONTRACT["family_ids"]) == RECONSTRUCTION_IDS
    for format_id in RECONSTRUCTION_IDS:
        expected = CONTRACT["valid"][format_id]
        path = paths[format_id]
        try:
            detected = sceneio.detect(path)
        except sceneio.FormatError:
            detected = "explicit_only"
        assert detected == expected["detected"]
        lower_inspection = _normalized_inspection(
            _lower_inspect(format_id, path)
        )
        public_inspection = _normalized_inspection(
            sceneio.inspect(path, format=format_id)
        )
        assert lower_inspection == expected["inspection"]
        assert public_inspection == expected["inspection"]
        artifact = _artifact(path)
        if format_id == "colmap_db":
            same_host = expected["artifact"]["same_host"]
            assert artifact["kind"] == expected["artifact"]["kind"]
            if (
                sys.platform == same_host["platform"]
                and public_inspection["metadata"]["sqlite_version"]
                == same_host["sqlite_version"]
            ):
                assert artifact["byte_size"] == same_host["byte_size"]
                assert artifact["sha256"] == same_host["sha256"]
        else:
            assert artifact == expected["artifact"]
        assert _record(sceneio.read(path, format=format_id)) == expected["record"]


@pytest.mark.parametrize("format_id", RECONSTRUCTION_IDS)
def test_retained_reconstruction_read_releases_path_and_keeps_values(
    tmp_path,
    format_id,
):
    path = _write_valid(
        tmp_path / f"retained-{format_id}",
        (format_id,),
    )[format_id]
    value = sceneio.read(path, format=format_id)
    expected = _record(value)
    gc.collect()
    _remove_path(path)
    assert _record(value) == expected


@pytest.mark.parametrize("format_id", RECONSTRUCTION_IDS)
def test_malformed_reconstruction_inspection_matches_parent_contract(
    tmp_path,
    format_id,
):
    expected = CONTRACT["malformed"][format_id]
    path = _malformed_path(tmp_path, format_id)
    with pytest.raises(Exception) as lower_error:
        _lower_inspect(format_id, path)
    assert type(lower_error.value).__name__ == expected["cause_type"]
    assert _normalized_message(lower_error.value, path) == (
        expected["cause_message"]
    )

    with pytest.raises(sceneio.FormatError) as public_error:
        sceneio.inspect(path, format=format_id)
    cause = public_error.value.__cause__
    assert type(cause).__name__ == expected["cause_type"]
    assert _normalized_message(cause, path) == expected["cause_message"]


def test_public_reconstruction_inspection_does_not_call_full_decoders(
    tmp_path,
    monkeypatch,
):
    paths = _write_valid(tmp_path / "valid")
    original = {
        format_id: registry.REGISTRY[format_id]
        for format_id in RECONSTRUCTION_IDS
    }

    def fail(*_args, **_kwargs):
        raise AssertionError("full reconstruction decoder called during inspection")

    for format_id, codec in original.items():
        registry.REGISTRY[format_id] = dataclasses.replace(codec, read=fail)
        monkeypatch.setattr(_core, _CORE_READ_NAMES[format_id], fail)
    try:
        for format_id, path in paths.items():
            assert sceneio.inspect(path, format=format_id).format == format_id
    finally:
        registry.REGISTRY.update(original)


@pytest.mark.parametrize("format_id", RECONSTRUCTION_IDS)
def test_retained_inspection_result_releases_reconstruction_path(
    tmp_path,
    format_id,
):
    path = _write_valid(tmp_path / "valid", (format_id,))[format_id]
    info = sceneio.inspect(path, format=format_id)
    released = path.with_name(path.name + ".released")
    path.rename(released)
    _remove_path(released)
    assert info.format == format_id


@pytest.mark.parametrize("format_id", RECONSTRUCTION_IDS)
def test_retained_inspection_exception_releases_reconstruction_path(
    tmp_path,
    format_id,
):
    path = _malformed_path(tmp_path, format_id)
    retained = None
    with pytest.raises(sceneio.FormatError) as captured:
        sceneio.inspect(path, format=format_id)
    retained = captured.value
    _remove_path(path)
    assert retained.__cause__ is not None


def _large_inspection_paths(root: Path) -> dict[str, Path]:
    root.mkdir()
    tum = root / "poses.tum"
    tum.write_bytes(b"0 1 2 3 0 0 0 1\n" * 300_000)

    g2o = root / "graph.g2o"
    g2o.write_bytes(
        b"".join(
            f"VERTEX_SE3:QUAT {index} 0 0 0 0 0 0 1\n".encode()
            for index in range(150_000)
        )
    )

    transforms = root / "transforms.json"
    frame = (
        b'{"file_path":"a.png","transform_matrix":'
        b"[[1,0,0,1],[0,1,0,2],[0,0,1,3],[0,0,0,1]]}"
    )
    transforms.write_bytes(
        b'{"camera_model":"PINHOLE","fl_x":500,"fl_y":510,'
        b'"cx":320,"cy":240,"w":640,"h":480,"frames":['
        + b",".join([frame] * 60_000)
        + b"]}"
    )

    colmap = root / "colmap"
    colmap.mkdir()
    point_count = 100_000
    large_reconstruction = _core.read_nvm(
        b"NVM_V3\n1\na.jpg 800 0.5 0.5 0.5 0.5 1 2 3 0 0\n"
        + str(point_count).encode()
        + b"\n"
        + b"1.5 -2.5 3.5 10 20 30 0\n" * point_count
        + b"0\n"
    )
    sceneio.write(
        large_reconstruction,
        colmap,
        format="colmap_sparse",
    )

    database = root / "database.db"
    sceneio.write(_database_record(), database, format="colmap_db")
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE inspection_padding(payload BLOB)")
        connection.execute(
            "INSERT INTO inspection_padding VALUES(zeroblob(?))",
            (8 * 1024 * 1024,),
        )

    openmvg = root / "sfm_data.json"
    sceneio.write(
        _records()["openmvg"],
        openmvg,
        format="openmvg",
    )
    encoded = openmvg.read_bytes()
    assert encoded.endswith(b"}")
    openmvg.write_bytes(
        encoded[:-1]
        + b',"inspection_padding":['
        + b"0," * (5 * 1024 * 1024 // 2)
        + b"0]}"
    )
    return {
        "tum": tum,
        "g2o": g2o,
        "transforms_json": transforms,
        "openmvg": openmvg,
        "colmap_sparse": colmap,
        "colmap_db": database,
    }


def test_large_reconstruction_inspection_has_bounded_python_allocation_and_releases_path(
    tmp_path,
):
    for format_id, path in _large_inspection_paths(
        tmp_path / "large"
    ).items():
        assert (
            sum(item.stat().st_size for item in path.iterdir())
            if path.is_dir()
            else path.stat().st_size
        ) > 4 * 1024 * 1024
        if format_id == "colmap_sparse":
            assert (path / "points3D.bin").stat().st_size > 4 * 1024 * 1024
        gc.collect()
        tracemalloc.start()
        try:
            info = sceneio.inspect(path, format=format_id)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert peak < 2 * 1024 * 1024, (format_id, peak)
        if format_id == "colmap_db":
            assert not path.with_name(path.name + "-journal").exists()
            assert not path.with_name(path.name + "-wal").exists()

        released = path.with_name(path.name + ".released")
        path.rename(released)
        _remove_path(released)
        assert info.format == format_id
