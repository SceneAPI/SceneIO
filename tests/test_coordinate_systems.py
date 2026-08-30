"""Coordinate contracts and explicit conversion verification."""

from __future__ import annotations

import ast
import dataclasses
import gc
import tomllib
from dataclasses import replace
from itertools import product
from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import _core
from sceneio.coordinates import CoordinateConvention
from sceneio.io._builtin_manifest import CANONICAL_BUILTIN_IDS
from sceneio.io._coordinate_manifest import FORMAT_COORDINATE_CONTRACTS

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = tomllib.loads(
    (ROOT / "tests/contracts/coordinate_systems_v1.toml").read_text(
        encoding="utf-8"
    )
)
CONVERSION_CONTRACT = tomllib.loads(
    (ROOT / "tests/contracts/coordinate_conversions_v1.toml").read_text(
        encoding="utf-8"
    )
)

_COLMAP_RECONSTRUCTION_ADAPTERS = frozenset(
    {
        "colmap_sparse",
        "colmap_sparse_txt",
        "bundler",
        "bal",
        "nvm",
        "openmvg",
    }
)


def _matrix_from_wxyz(quaternion: np.ndarray, translation: np.ndarray) -> np.ndarray:
    """Independent Hamilton oracle used only by these tests."""

    w, x, y, z = quaternion / np.linalg.norm(quaternion)
    matrix = np.eye(4)
    matrix[:3, :3] = (
        (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
        (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
        (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
    )
    matrix[:3, 3] = translation
    return matrix


def _ordered_quaternion(quaternion: np.ndarray, order: str) -> np.ndarray:
    if order == "wxyz":
        return quaternion
    if order == "xyzw":
        return quaternion[[1, 2, 3, 0]]
    raise AssertionError(f"unrecognized contract quaternion order {order!r}")


def _wxyz_quaternion(quaternion: np.ndarray, order: str) -> np.ndarray:
    if order == "wxyz":
        return quaternion
    if order == "xyzw":
        return quaternion[[3, 0, 1, 2]]
    raise AssertionError(f"unrecognized contract quaternion order {order!r}")


def test_colmap_canonical_contract_is_explicit_and_not_falsely_metric():
    convention = sceneio.COLMAP_COORDINATES
    assert convention.camera_axes == "opencv"
    assert convention.handedness == "right_handed"
    assert convention.pose_direction == "world_to_camera"
    assert convention.quaternion_order == "wxyz"
    assert convention.quaternion_algebra == "hamilton"
    assert convention.image_origin == "upper_left"
    assert convention.pixel_center == (0.5, 0.5)
    assert convention.depth_interpretation == "camera_z"
    assert convention.world_frame == "arbitrary"
    assert convention.scale_class == "arbitrary"
    assert convention.scale_to_meters is None


def test_coordinate_value_types_are_frozen_and_reject_contradictions():
    with pytest.raises(dataclasses.FrozenInstanceError):
        sceneio.COLMAP_COORDINATES.camera_axes = "opengl"
    with pytest.raises(ValueError, match="metric conventions require"):
        CoordinateConvention(name="bad", scale_class="metric")
    with pytest.raises(ValueError, match="only metric conventions"):
        CoordinateConvention(
            name="bad",
            scale_class="arbitrary",
            scale_to_meters=1.0,
        )
    with pytest.raises(ValueError, match="pixel_center requires"):
        CoordinateConvention(name="bad", pixel_center=(0.5, 0.5))
    with pytest.raises(ValueError, match="invalid domain"):
        sceneio.FormatCoordinateContract(
            "fixed",
            ("volume",),
            sceneio.COLMAP_COORDINATES,
            "match",
            "supported",
            "reference",
        )
    with pytest.raises(ValueError, match="conversion policy"):
        sceneio.FormatCoordinateContract(
            "fixed",
            ("spatial",),
            sceneio.COLMAP_COORDINATES,
            "match",
            "automatic",
            "reference",
        )
    with pytest.raises(ValueError, match="resolve conventions per file"):
        sceneio.FormatCoordinateContract(
            "file_declared",
            ("spatial",),
            sceneio.COLMAP_COORDINATES,
            "preserve",
            "requires_context",
            "reference",
        )

    quaternions = np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float64)
    translations = np.zeros((1, 3), dtype=np.float64)
    with pytest.raises(ValueError, match="need quaternions"):
        _core.pose_storage(quaternions[..., None], translations)
    with pytest.raises(ValueError, match="timestamps"):
        _core.pose_storage(
            quaternions,
            translations,
            timestamps=np.zeros((1, 1), dtype=np.float64),
        )
    with pytest.raises(ValueError, match="scale_to_meters"):
        _core.pose_storage(
            quaternions,
            translations,
            scale_to_meters=0.0,
        )


def test_checked_manifest_exactly_covers_registry_in_registry_order():
    assert CONTRACT["schema_version"] == 1
    assert CONTRACT["canonical"] == "colmap"
    assert tuple(CONTRACT["formats"]) == CANONICAL_BUILTIN_IDS
    actual = {
        format_id: f"{value.status}:{','.join(value.domains)}"
        for format_id, value in FORMAT_COORDINATE_CONTRACTS.items()
    }
    assert actual == CONTRACT["formats"]
    assert tuple(sceneio.capabilities()) == CANONICAL_BUILTIN_IDS
    assert all(
        sceneio.capabilities(format_id).coordinates is contract
        for format_id, contract in FORMAT_COORDINATE_CONTRACTS.items()
    )


def test_checked_conversion_contract_pins_the_public_semantics():
    assert CONVERSION_CONTRACT["schema_version"] == 1
    assert CONVERSION_CONTRACT["api"] == "sceneio.convert_coordinates"
    assert CONVERSION_CONTRACT["default_target"] == "colmap"
    assert CONVERSION_CONTRACT["world_transform_direction"] == (
        "source_world_meters_to_target_world_meters"
    )
    assert CONVERSION_CONTRACT["world_transform_translation_unit"] == "meters"
    assert CONVERSION_CONTRACT["identity_policy"] == (
        "only_qualified_records_may_return_identity"
    )
    assert CONVERSION_CONTRACT["source_override"] == (
        "may_refine_unknown_or_arbitrary_fields_but_must_not_conflict_with_declared_fields"
    )
    assert tuple(CONVERSION_CONTRACT["qualified"]) == (
        "PosedViewSet",
        "PointCloud",
        "GaussianCloud",
        "Mesh",
    )
    assert CONVERSION_CONTRACT["qualified"]["PosedViewSet"]["world_transform"] == (
        "proper_rigid"
    )
    assert CONVERSION_CONTRACT["qualified"]["PointCloud"]["world_transform"] == (
        "invertible_affine"
    )
    assert CONVERSION_CONTRACT["qualified"]["GaussianCloud"]["world_transform"] == (
        "orientation_preserving_similarity"
    )
    assert CONVERSION_CONTRACT["qualified"]["GaussianCloud"]["directional_sh"] == (
        "identity_rotation_only"
    )
    assert CONVERSION_CONTRACT["qualified"]["Mesh"]["world_transform"] == (
        "orientation_preserving_invertible_affine"
    )
    assert CONVERSION_CONTRACT["unqualified"]["identity_still_refuses"] is True

    per_format = CONVERSION_CONTRACT["format_verification"]
    assert tuple(entry["id"] for entry in per_format) == CANONICAL_BUILTIN_IDS
    assert len({entry["id"] for entry in per_format}) == len(per_format)
    for entry in per_format:
        assert set(entry) == {
            "id",
            "decode",
            "encode",
            "conversion",
            "oracle",
            "tests",
        }
        format_id = entry["id"]
        contract = FORMAT_COORDINATE_CONTRACTS[format_id]

        if format_id in _COLMAP_RECONSTRUCTION_ADAPTERS:
            expected_decode = "normalize_to_colmap"
            expected_encode = "encode_from_colmap"
            expected_conversion = "adapter"
        elif contract.status == "fixed":
            expected_decode = "preserve_fixed"
            expected_encode = "unsupported" if format_id == "rtmv" else "require_fixed"
            expected_conversion = (
                "direct"
                if contract.conversion == "supported"
                else contract.conversion
            )
        elif contract.status == "file_declared":
            expected_decode = expected_encode = "preserve_declared"
            expected_conversion = "requires_context"
        elif contract.status == "unspecified":
            expected_decode = "preserve_unspecified"
            expected_encode = "require_unspecified"
            expected_conversion = "requires_context"
        else:
            expected_decode = expected_encode = "not_applicable"
            expected_conversion = "not_applicable"

        assert entry["decode"] == expected_decode, format_id
        assert entry["encode"] == expected_encode, format_id
        assert entry["conversion"] == expected_conversion, format_id
        assert bool(sceneio.codecs()[format_id].write) is (
            entry["encode"] != "unsupported"
        )
        assert isinstance(entry["oracle"], str) and entry["oracle"].strip()
        assert contract.reference.startswith(("https://", "docs/"))
        assert entry["tests"]
        evidence = []
        test_names = []
        for relative_path in entry["tests"]:
            path = ROOT / relative_path
            assert path.is_file(), (format_id, relative_path)
            assert path.parent == ROOT / "tests/codecs"
            source = path.read_text(encoding="utf-8")
            evidence.append(source.lower())
            test_names.extend(
                node.name.lower()
                for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.FunctionDef)
                and node.name.startswith("test_")
            )
        joined = "\n".join(evidence)
        assert "oracle" in joined or "parity" in joined, format_id
        assert any(
            marker in name
            for name in test_names
            for marker in ("read", "decode", "roundtrip", "parity")
        ), format_id
        if entry["encode"] != "unsupported":
            assert any(
                marker in name
                for name in test_names
                for marker in ("writ", "encode", "roundtrip", "parity")
            ), format_id


def test_extension_capability_uses_explicit_unspecified_fallback():
    codec = sceneio.Codec(
        "extension_probe",
        (".probe",),
        lambda path: path,
        None,
        None,
        "probe",
    )
    assert codec.capabilities().coordinates is sceneio.UNSPECIFIED_FORMAT_COORDINATES


def test_native_record_coordinate_views_are_additive():
    point = _core.point_cloud(
        np.zeros((1, 3), dtype=np.float32),
        coordinate_frame="enu",
        scale_to_meters=0.01,
    )
    assert point.coordinates.world_frame == "enu"
    assert point.coordinates.up_axis == "z"
    assert point.coordinates.scale_to_meters == 0.01

    reconstruction = _core.read_bal(b"0 0 0\n")
    assert reconstruction.coordinates == sceneio.COLMAP_COORDINATES

    image = _core.image(np.zeros((2, 3, 3), dtype=np.uint8))
    assert image.coordinates == sceneio.IMAGE_COORDINATES


def test_python_contract_records_expose_scoped_coordinate_views():
    mask = sceneio.Mask(np.zeros((2, 3), dtype=np.bool_))
    assert mask.coordinates == sceneio.IMAGE_COORDINATES

    semantic = sceneio.SemanticMap(
        np.zeros((2, 3), dtype=np.int32),
        -1,
    )
    instance = sceneio.InstanceMap(
        np.zeros((2, 3), dtype=np.int64),
        0,
    )
    panoptic = sceneio.PanopticMap(semantic, instance)
    assert semantic.coordinates == sceneio.IMAGE_COORDINATES
    assert instance.coordinates == sceneio.IMAGE_COORDINATES
    assert panoptic.coordinates == sceneio.IMAGE_COORDINATES

    features = sceneio.feature_set(
        np.array([[10.5, 20.5]], dtype=np.float32)
    )
    pairs = sceneio.PairCorrespondences.from_coordinates(
        np.array([[10.5, 20.5]], dtype=np.float32),
        np.array([[30.5, 40.5]], dtype=np.float32),
    )
    assert features.coordinates == sceneio.IMAGE_COORDINATES
    assert pairs.coordinates == sceneio.IMAGE_COORDINATES

    indexed = sceneio.PairCorrespondences.from_indices(
        np.array([[0, 0]], dtype=np.uint32)
    )
    assert indexed.coordinates is None

    native_colmap_features = _core.feature_set(
        np.array([[10.5, 20.5]], dtype=np.float32)
    )
    native_hloc_features = _core.feature_set(
        np.array([[10.0, 20.0]], dtype=np.float32),
        pixel_center=(0.0, 0.0),
    )
    assert native_colmap_features.coordinates.pixel_center == (0.5, 0.5)
    assert native_hloc_features.coordinates.pixel_center == (0.0, 0.0)

    hloc_graph = sceneio.CorrespondenceGraph(
        features={
            "a": sceneio.feature_set(
                np.array([[10.0, 20.0]], dtype=np.float32),
                pixel_center=(0.0, 0.0),
            ),
            "b": sceneio.feature_set(
                np.array([[30.0, 40.0]], dtype=np.float32),
                pixel_center=(0.0, 0.0),
            ),
        },
        pairs={("a", "b"): indexed},
    )
    assert hloc_graph.coordinates.pixel_center == (0.0, 0.0)

    frame = sceneio.FrameMeta(
        world_frame="capture_rig",
        scale="metric",
        scale_provenance="prior_anchored",
    )
    assert frame.coordinates.world_frame == "reference"
    assert frame.coordinates.reference_frame == "capture_rig"
    assert frame.coordinates.scale_to_meters == 1.0

    tracked = sceneio.point_cloud(
        np.zeros((1, 3), dtype=np.float32),
        tracks=((sceneio.TrackObservation("image", 0),),),
    )
    assert tracked.coordinates.world_frame == "unknown"


def test_inspection_reports_fixed_unspecified_and_file_declared_conventions():
    image = sceneio.Inspection("png", "image", 10)
    assert image.coordinates == sceneio.IMAGE_COORDINATES
    tensor = sceneio.Inspection("npy", "tensor", 10)
    assert tensor.coordinates == sceneio.UNKNOWN_COORDINATES
    usd = sceneio.Inspection(
        "usd",
        "scene_graph",
        10,
        metadata={"up_axis": "z", "meters_per_unit": 0.01},
    )
    assert usd.coordinates.up_axis == "z"
    assert usd.coordinates.scale_to_meters == 0.01


def test_opengl_c2w_to_colmap_w2c_matches_independent_matrix_oracle():
    angle = np.deg2rad(37.0)
    source_quaternion = np.array(
        [[np.cos(angle / 2), 0.0, np.sin(angle / 2), 0.0]],
        dtype=np.float64,
    )
    source_translation = np.array([[1.25, -2.5, 4.75]], dtype=np.float64)
    camera = _core.camera_intrinsics(
        1,
        640,
        480,
        np.array([500.0, 510.0, 320.5, 240.5], dtype=np.float64),
    )
    source = _core.pose_storage(
        source_quaternion,
        source_translation,
        names=["view.png"],
        quaternion_order="wxyz",
        pose_convention="camera_to_world",
        axis_frame="opengl",
        scale_to_meters=1.0,
        camera_indices=np.array([0], dtype=np.int32),
        cameras=[camera],
    )
    converted = sceneio.convert_coordinates(source)

    source_c2w = _matrix_from_wxyz(
        source_quaternion[0],
        source_translation[0],
    )
    flip = np.diag((1.0, -1.0, -1.0, 1.0))
    expected_w2c = flip @ np.linalg.inv(source_c2w)
    actual_w2c = _matrix_from_wxyz(
        np.asarray(converted.quaternions)[0],
        np.asarray(converted.translations)[0],
    )
    np.testing.assert_allclose(actual_w2c, expected_w2c, atol=1e-12)
    pycolmap = pytest.importorskip("pycolmap")
    quaternion_xyzw = np.asarray(converted.quaternions)[0][[1, 2, 3, 0]]
    oracle = pycolmap.Rigid3d(
        pycolmap.Rotation3d(quaternion_xyzw),
        np.asarray(converted.translations)[0],
    )
    np.testing.assert_allclose(np.asarray(oracle.matrix()), expected_w2c[:3])
    assert converted.pose_convention == "world_to_camera"
    assert converted.axis_frame == "opencv"
    assert converted.quaternion_order == "wxyz"
    assert converted.names == ["view.png"]
    np.testing.assert_array_equal(converted.camera_indices, [0])
    assert converted.cameras[0].model_id == 1

    camera_center = -actual_w2c[:3, :3].T @ actual_w2c[:3, 3]
    np.testing.assert_allclose(camera_center, source_c2w[:3, 3])

    del source, camera
    gc.collect()
    np.testing.assert_allclose(converted.translations, expected_w2c[:3, 3][None])
    np.testing.assert_allclose(converted.cameras[0].params, [500.0, 510.0, 320.5, 240.5])


def test_pose_conversion_round_trip_is_geometrically_exact():
    source = _core.pose_storage(
        np.array([[0.8, 0.1, -0.3, 0.5]], dtype=np.float64),
        np.array([[2.0, -7.0, 11.0]], dtype=np.float64),
        quaternion_order="wxyz",
        pose_convention="camera_to_world",
        axis_frame="opengl",
        scale_to_meters=0.01,
    )
    canonical = sceneio.convert_coordinates(source)
    restored = sceneio.convert_coordinates(canonical, target=source.coordinates)
    expected = _matrix_from_wxyz(
        np.asarray(source.quaternions)[0],
        np.asarray(source.translations)[0],
    )
    actual = _matrix_from_wxyz(
        np.asarray(restored.quaternions)[0],
        np.asarray(restored.translations)[0],
    )
    np.testing.assert_allclose(actual, expected, atol=1e-12)

    xyzw_source = _core.pose_storage(
        np.array([[0.0, 0.0, 0.0, 1.0]], dtype=np.float64),
        np.array([[100.0, 0.0, 0.0]], dtype=np.float64),
        quaternion_order="xyzw",
        pose_convention="camera_to_world",
        axis_frame="opencv",
        scale_to_meters=0.01,
    )
    metric_target = replace(
        sceneio.COLMAP_COORDINATES,
        name="metric_colmap_target",
        scale_class="metric",
        scale_to_meters=1.0,
    )
    scaled = sceneio.convert_coordinates(xyzw_source, target=metric_target)
    np.testing.assert_allclose(scaled.quaternions, [[1.0, 0.0, 0.0, 0.0]])
    np.testing.assert_allclose(scaled.translations, [[-1.0, 0.0, 0.0]])
    assert scaled.scale_to_meters == 1.0


_POSE_CONTRACT = CONVERSION_CONTRACT["qualified"]["PosedViewSet"]
_POSE_CASES = list(
    product(
        _POSE_CONTRACT["camera_axes"],
        _POSE_CONTRACT["pose_directions"],
        _POSE_CONTRACT["quaternion_orders"],
        _POSE_CONTRACT["camera_axes"],
        _POSE_CONTRACT["pose_directions"],
        _POSE_CONTRACT["quaternion_orders"],
    )
)


def _assert_pose_contract_case(
    source_axes,
    source_direction,
    source_order,
    target_axes,
    target_direction,
    target_order,
):
    source_scale = 0.01
    target_scale = 0.1
    source_w2c_quaternion = np.array(
        [0.81240384, 0.20056212, -0.30084318, 0.45828484],
        dtype=np.float64,
    )
    source_w2c_quaternion /= np.linalg.norm(source_w2c_quaternion)
    source_w2c = _matrix_from_wxyz(
        source_w2c_quaternion,
        np.array([1.25, -2.5, 4.75], dtype=np.float64),
    )
    if source_direction == "world_to_camera":
        source_pose = source_w2c
        source_quaternion = source_w2c_quaternion
    else:
        source_pose = np.linalg.inv(source_w2c)
        source_quaternion = source_w2c_quaternion * np.array(
            [1.0, -1.0, -1.0, -1.0]
        )

    record = _core.pose_storage(
        _ordered_quaternion(source_quaternion, source_order)[None],
        (source_pose[:3, 3] / source_scale)[None],
        quaternion_order=source_order,
        pose_convention=source_direction,
        axis_frame=source_axes,
        scale_to_meters=source_scale,
    )
    target = replace(
        sceneio.COLMAP_COORDINATES,
        name="contract_matrix_target",
        camera_axes=target_axes,
        pose_direction=target_direction,
        quaternion_order=target_order,
        scale_class="metric",
        scale_to_meters=target_scale,
    )
    world_quaternion = np.array(
        [0.9659258263, 0.0, 0.0, 0.2588190451],
        dtype=np.float64,
    )
    world_transform = _matrix_from_wxyz(
        world_quaternion,
        np.array([0.3, -0.4, 0.7], dtype=np.float64),
    )

    converted = sceneio.convert_coordinates(
        record,
        target=target,
        world_transform=world_transform,
    )
    camera_basis = (
        np.eye(4)
        if source_axes == target_axes
        else np.diag((1.0, -1.0, -1.0, 1.0))
    )
    expected_w2c = camera_basis @ source_w2c @ np.linalg.inv(world_transform)
    expected_pose = (
        expected_w2c
        if target_direction == "world_to_camera"
        else np.linalg.inv(expected_w2c)
    )
    actual_quaternion = _wxyz_quaternion(
        np.asarray(converted.quaternions)[0],
        target_order,
    )
    actual_pose = _matrix_from_wxyz(
        actual_quaternion,
        np.asarray(converted.translations)[0] * target_scale,
    )
    np.testing.assert_allclose(
        actual_pose,
        expected_pose,
        atol=2e-10,
        err_msg=str(
            (
                source_axes,
                source_direction,
                source_order,
                target_axes,
                target_direction,
                target_order,
            )
        ),
    )


def test_pose_contract_cartesian_product_matches_matrix_oracle():
    for case in _POSE_CASES:
        _assert_pose_contract_case(*case)


def test_pose_world_frame_change_requires_an_explicit_rigid_map():
    record = _core.pose_storage(
        np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float64),
        np.zeros((1, 3), dtype=np.float64),
    )
    referenced_source = replace(
        record.coordinates,
        name="rig_relative",
        world_frame="reference",
        reference_frame="capture_rig",
    )
    with pytest.raises(ValueError, match="world-frame changes require"):
        sceneio.convert_coordinates(record, source=referenced_source)

    converted = sceneio.convert_coordinates(
        record,
        source=referenced_source,
        world_transform=np.eye(4),
    )
    np.testing.assert_array_equal(converted.translations, [[0.0, 0.0, 0.0]])

    almost_rigid = np.eye(4)
    almost_rigid[0, 0] = 1.0 + 5e-6
    with pytest.raises(ValueError, match="must be rigid"):
        sceneio.convert_coordinates(record, world_transform=almost_rigid)


def test_point_conversion_transforms_basis_origin_normals_and_vectors():
    source = _core.point_cloud(
        np.array([[1.0, 2.0, 3.0]], dtype=np.float32),
        normals=np.array([[0.0, 1.0, 0.0]], dtype=np.float32),
        coordinate_frame="opengl",
        scale_to_meters=0.01,
        origin=np.array([10.0, 20.0, 30.0], dtype=np.float64),
        velocities=np.array([[4.0, 5.0, 6.0]], dtype=np.float32),
    )
    converted = sceneio.convert_coordinates(source)
    np.testing.assert_array_equal(converted.positions, [[1.0, -2.0, -3.0]])
    np.testing.assert_array_equal(converted.normals, [[0.0, -1.0, 0.0]])
    np.testing.assert_array_equal(converted.velocities, [[4.0, -5.0, -6.0]])
    np.testing.assert_array_equal(converted.origin, [10.0, -20.0, -30.0])
    assert converted.coordinate_frame == "opencv"
    assert converted.scale_to_meters == 0.01


def test_point_contract_converts_lengths_and_preserves_nonspatial_fields():
    source = _core.point_cloud(
        np.array([[1.0, 2.0, 3.0], [-4.0, 5.0, -6.0]], dtype=np.float32),
        colors=np.array([[1, 2, 3], [4, 5, 6]], dtype=np.uint8),
        colors16=np.array([[100, 200, 300], [400, 500, 600]], dtype=np.uint16),
        normals=np.array([[0.0, 1.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float32),
        intensity=np.array([7.0, 8.0], dtype=np.float32),
        coordinate_frame="opengl",
        scale_to_meters=0.01,
        intensity_range="u16",
        origin=np.array([10.0, 20.0, 30.0], dtype=np.float64),
        width=1,
        height=2,
        display_colors=np.array(
            [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]], dtype=np.float32
        ),
        display_opacities=np.array([0.25, 0.75], dtype=np.float32),
        widths=np.array([2.0, 4.0], dtype=np.float32),
        ids=np.array([11, 12], dtype=np.int64),
        velocities=np.array([[4.0, 5.0, 6.0], [7.0, 8.0, 9.0]], dtype=np.float32),
        accelerations=np.array(
            [[0.4, 0.5, 0.6], [0.7, 0.8, 0.9]], dtype=np.float32
        ),
        display_color_space="linear",
    )
    target = replace(
        sceneio.COLMAP_COORDINATES,
        name="metric_colmap_points",
        scale_class="metric",
        scale_to_meters=1.0,
    )
    converted = sceneio.convert_coordinates(source, target=target)

    np.testing.assert_allclose(
        converted.positions,
        [[0.01, -0.02, -0.03], [-0.04, -0.05, 0.06]],
    )
    np.testing.assert_allclose(converted.origin, [0.1, -0.2, -0.3])
    np.testing.assert_allclose(converted.widths, [0.02, 0.04])
    np.testing.assert_allclose(
        converted.velocities,
        [[0.04, -0.05, -0.06], [0.07, -0.08, -0.09]],
    )
    np.testing.assert_allclose(
        converted.accelerations,
        [[0.004, -0.005, -0.006], [0.007, -0.008, -0.009]],
    )
    np.testing.assert_array_equal(converted.colors, source.colors)
    np.testing.assert_array_equal(converted.colors16, source.colors16)
    np.testing.assert_array_equal(converted.intensities, source.intensities)
    np.testing.assert_array_equal(converted.display_colors, source.display_colors)
    np.testing.assert_array_equal(
        converted.display_opacities,
        source.display_opacities,
    )
    np.testing.assert_array_equal(converted.ids, source.ids)
    assert (converted.width, converted.height) == (1, 2)
    assert converted.intensity_range == "u16"
    assert converted.display_color_space == "linear"
    assert converted.coordinate_frame == "opencv"
    assert converted.scale_to_meters == 1.0

    converted.positions[0, 0] = 99.0
    assert source.positions[0, 0] == 1.0
    del source
    gc.collect()
    assert converted.positions[0, 0] == 99.0
    np.testing.assert_array_equal(converted.ids, [11, 12])


def test_point_contract_converts_enu_ned_and_refuses_ambiguous_width_scale():
    source = _core.point_cloud(
        np.array([[1.0, 2.0, 3.0]], dtype=np.float32),
        coordinate_frame="enu",
        origin=np.array([10.0, 20.0, 30.0], dtype=np.float64),
    )
    ned = CoordinateConvention(
        name="ned_metric",
        handedness="right_handed",
        world_frame="ned",
        scale_class="metric",
        scale_to_meters=1.0,
    )
    converted = sceneio.convert_coordinates(source, target=ned)
    np.testing.assert_array_equal(converted.positions, [[2.0, 1.0, -3.0]])
    np.testing.assert_array_equal(converted.origin, [20.0, 10.0, -30.0])
    restored = sceneio.convert_coordinates(converted, target=source.coordinates)
    np.testing.assert_array_equal(restored.positions, source.positions)
    np.testing.assert_array_equal(restored.origin, source.origin)

    widths = _core.point_cloud(
        np.array([[1.0, 2.0, 3.0]], dtype=np.float32),
        widths=np.array([2.0], dtype=np.float32),
        coordinate_frame="opengl",
    )
    anisotropic = np.diag((2.0, 3.0, 4.0, 1.0))
    with pytest.raises(ValueError, match="scalar widths require a similarity"):
        sceneio.convert_coordinates(widths, world_transform=anisotropic)
    np.testing.assert_array_equal(widths.widths, [2.0])

    affine_source = _core.point_cloud(
        np.array([[1.0, 2.0, 3.0]], dtype=np.float32),
        normals=np.array([[1.0, 1.0, 0.0]], dtype=np.float32),
        coordinate_frame="opengl",
    )
    affine = sceneio.convert_coordinates(
        affine_source,
        world_transform=anisotropic,
    )
    np.testing.assert_array_equal(affine.positions, [[2.0, 6.0, 12.0]])
    expected_normal = np.array([0.5, 1.0 / 3.0, 0.0])
    expected_normal /= np.linalg.norm(expected_normal)
    np.testing.assert_allclose(affine.normals[0], expected_normal, atol=1e-7)


def test_scalar_width_similarity_check_is_independent_of_unit_scale():
    source = _core.point_cloud(
        np.array([[1.0, 2.0, 3.0]], dtype=np.float32),
        widths=np.array([2.0], dtype=np.float32),
        coordinate_frame="opengl",
        scale_to_meters=1e-6,
    )
    anisotropic = np.diag((1.0, 1.5, 1.0, 1.0))

    with pytest.raises(ValueError, match="scalar widths require a similarity"):
        sceneio.convert_coordinates(
            source,
            target=replace(
                sceneio.COLMAP_COORDINATES,
                name="metric_target",
                scale_class="metric",
                scale_to_meters=1.0,
            ),
            world_transform=anisotropic,
        )


def test_mesh_contract_preserves_payload_and_world_geometry():
    positions = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        dtype=np.float32,
    )
    local_transform = np.array(
        [
            [1.0, 0.0, 0.0, 5.0],
            [0.0, 1.0, 0.0, 6.0],
            [0.0, 0.0, 1.0, 7.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    source = _core.mesh(
        positions,
        np.array([0, 3], dtype=np.uint64),
        np.array([0, 1, 2], dtype=np.uint64),
        vertex_normals=np.array(
            [[0.0, 0.0, 1.0]] * 3,
            dtype=np.float32,
        ),
        corner_normals=np.array(
            [[0.0, 1.0, 0.0]] * 3,
            dtype=np.float32,
        ),
        vertex_uvs=np.array(
            [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
            dtype=np.float32,
        ),
        corner_uvs=np.array(
            [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]],
            dtype=np.float32,
        ),
        vertex_colors=np.arange(12, dtype=np.uint8).reshape(3, 4),
        corner_colors=np.arange(12, 24, dtype=np.uint8).reshape(3, 4),
        primitive_offsets=np.array([0, 1], dtype=np.uint64),
        primitive_materials=np.array([-1], dtype=np.int32),
        face_smoothing_groups=np.array([7], dtype=np.uint32),
        primitive_object_names=["object"],
        primitive_group_names=["group"],
        coordinate_frame="opengl",
        scale_to_meters=0.01,
        local_transform=local_transform,
        vertex_display_colors=np.full((3, 3), 0.25, dtype=np.float32),
        corner_display_colors=np.full((3, 3), 0.75, dtype=np.float32),
        vertex_display_opacities=np.array([0.1, 0.2, 0.3], dtype=np.float32),
        corner_display_opacities=np.array([0.4, 0.5, 0.6], dtype=np.float32),
        display_color_space="linear",
        orientation="right_handed",
    )
    target = replace(
        sceneio.COLMAP_COORDINATES,
        name="metric_colmap_mesh",
        scale_class="metric",
        scale_to_meters=1.0,
    )
    world_transform = np.array(
        [
            [1.0, 0.2, 0.0, 0.3],
            [0.0, 2.0, 0.1, -0.4],
            [0.0, 0.0, 1.5, 0.7],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    converted = sceneio.convert_coordinates(
        source,
        target=target,
        world_transform=world_transform,
    )

    numeric_transform = world_transform.copy()
    numeric_transform[:3, :3] *= 0.01
    source_h = np.column_stack((positions, np.ones(len(positions))))
    expected_positions = (source_h @ numeric_transform.T)[:, :3]
    np.testing.assert_allclose(converted.positions, expected_positions)
    expected_local = (
        numeric_transform
        @ local_transform
        @ np.linalg.inv(numeric_transform)
    )
    np.testing.assert_allclose(converted.local_transform, expected_local)
    converted_h = np.column_stack(
        (np.asarray(converted.positions), np.ones(converted.num_vertices))
    )
    source_world = (source_h @ local_transform.T)[:, :3]
    target_world = (converted_h @ converted.local_transform.T)[:, :3]
    expected_world = (
        np.column_stack((source_world, np.ones(len(source_world))))
        @ numeric_transform.T
    )[:, :3]
    np.testing.assert_allclose(target_world, expected_world)

    np.testing.assert_array_equal(converted.face_offsets, source.face_offsets)
    np.testing.assert_array_equal(converted.face_indices, source.face_indices)
    np.testing.assert_array_equal(converted.vertex_uvs, source.vertex_uvs)
    np.testing.assert_array_equal(converted.corner_uvs, source.corner_uvs)
    np.testing.assert_array_equal(converted.vertex_colors, source.vertex_colors)
    np.testing.assert_array_equal(converted.corner_colors, source.corner_colors)
    np.testing.assert_array_equal(
        converted.face_smoothing_groups,
        source.face_smoothing_groups,
    )
    assert converted.primitive_object_names == ["object"]
    assert converted.primitive_group_names == ["group"]
    assert converted.display_color_space == "linear"
    assert converted.orientation == "right_handed"
    assert not source.has_double_sided
    assert not converted.has_double_sided
    assert converted.double_sided is None
    del source
    gc.collect()
    np.testing.assert_array_equal(converted.face_indices, [0, 1, 2])
    assert converted.primitive_object_names == ["object"]


@pytest.mark.parametrize("double_sided", [None, False, True])
def test_mesh_contract_preserves_double_sided_presence(double_sided):
    source = _core.mesh(
        np.zeros((3, 3), dtype=np.float32),
        np.array([0, 3], dtype=np.uint64),
        np.array([0, 1, 2], dtype=np.uint64),
        coordinate_frame="opengl",
        double_sided=double_sided,
    )
    converted = sceneio.convert_coordinates(source)
    assert converted.has_double_sided is (double_sided is not None)
    assert converted.double_sided is double_sided


def test_conversion_refuses_unqualified_viewpoints_and_nonrigid_pose_frames():
    cloud = _core.point_cloud(
        np.zeros((1, 3), dtype=np.float32),
        coordinate_frame="opengl",
        viewpoint=np.array(
            [1.0, 2.0, 3.0, 1.0, 0.0, 0.0, 0.0],
            dtype=np.float64,
        ),
    )
    with pytest.raises(ValueError, match="acquisition viewpoint"):
        sceneio.convert_coordinates(cloud)

    views = _core.pose_storage(
        np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float64),
        np.zeros((1, 3), dtype=np.float64),
        axis_frame="opengl",
    )
    shear = np.eye(4)
    shear[0, 1] = 0.25
    with pytest.raises(ValueError, match="must be rigid"):
        sceneio.convert_coordinates(views, world_transform=shear)

    with pytest.raises(ValueError, match="pixel convention"):
        sceneio.convert_coordinates(
            views,
            target=replace(
                sceneio.COLMAP_COORDINATES,
                name="hloc_pixel_target",
                pixel_center=(0.0, 0.0),
            ),
        )

    mesh = _core.mesh(
        np.zeros((3, 3), dtype=np.float32),
        np.array([0, 3], dtype=np.uint64),
        np.array([0, 1, 2], dtype=np.uint64),
        coordinate_frame="opengl",
    )
    reflection = np.diag((-1.0, 1.0, 1.0, 1.0))
    with pytest.raises(ValueError, match="winding policy"):
        sceneio.convert_coordinates(mesh, world_transform=reflection)

    with pytest.raises(ValueError, match="not representable"):
        sceneio.convert_coordinates(
            _core.point_cloud(
                np.zeros((1, 3), dtype=np.float32),
                coordinate_frame="opencv",
            ),
            target=replace(
                sceneio.COLMAP_COORDINATES,
                name="ecef_target",
                camera_axes="not_applicable",
                world_frame="ecef",
            ),
            world_transform=np.eye(4),
        )


def test_unknown_geometry_requires_an_explicit_source_or_transform():
    point = _core.point_cloud(np.zeros((1, 3), dtype=np.float32))
    with pytest.raises(ValueError, match="requires world_transform"):
        sceneio.convert_coordinates(point)

    translated = sceneio.convert_coordinates(
        point,
        world_transform=np.array(
            [
                [1.0, 0.0, 0.0, 3.0],
                [0.0, 1.0, 0.0, 4.0],
                [0.0, 0.0, 1.0, 5.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        ),
    )
    np.testing.assert_array_equal(translated.origin, [3.0, 4.0, 5.0])


def test_nonspatial_and_unqualified_conversions_refuse_clearly():
    image = _core.image(np.zeros((2, 3, 3), dtype=np.uint8))
    with pytest.raises(TypeError, match="not qualified"):
        sceneio.convert_coordinates(image)

    reconstruction = _core.read_bal(b"0 0 0\n")
    conflicting_source = replace(
        sceneio.COLMAP_COORDINATES,
        name="conflicting_reconstruction_source",
        camera_axes="opengl",
    )
    with pytest.raises(TypeError, match="not qualified"):
        sceneio.convert_coordinates(
            reconstruction,
            source=conflicting_source,
        )


def test_unqualified_records_cannot_bypass_dispatch_via_identity_target():
    image = _core.image(np.zeros((2, 3, 3), dtype=np.uint8))
    reconstruction = _core.read_bal(b"0 0 0\n")
    cases = (
        (image, sceneio.IMAGE_COORDINATES),
        (reconstruction, sceneio.COLMAP_COORDINATES),
    )
    for record, target in cases:
        with pytest.raises(TypeError, match="not qualified"):
            sceneio.convert_coordinates(record, target=target)


def test_conversion_rejects_falsey_noncontract_source_and_invalid_target():
    point = _core.point_cloud(
        np.zeros((1, 3), dtype=np.float32),
        coordinate_frame="opencv",
    )
    with pytest.raises(TypeError, match="source must be"):
        sceneio.convert_coordinates(point, source=0)
    with pytest.raises(TypeError, match="target must be"):
        sceneio.convert_coordinates(point, target=None)

    conflicting = replace(
        point.coordinates,
        name="conflicting_source",
        camera_axes="opengl",
    )
    with pytest.raises(ValueError, match="conflicts with record camera_axes"):
        sceneio.convert_coordinates(point, source=conflicting, target=conflicting)

    unknown = _core.point_cloud(np.array([[1.0, 2.0, 3.0]], dtype=np.float32))
    declared_opengl = replace(
        sceneio.COLMAP_COORDINATES,
        name="caller_declared_opengl",
        camera_axes="opengl",
        scale_class="metric",
        scale_to_meters=1.0,
    )
    converted = sceneio.convert_coordinates(unknown, source=declared_opengl)
    np.testing.assert_array_equal(converted.positions, [[1.0, -2.0, -3.0]])


def test_identity_source_override_refines_unknown_record_metadata():
    unknown = _core.point_cloud(
        np.array([[1.0, 2.0, 3.0]], dtype=np.float32)
    )
    declared = replace(
        sceneio.COLMAP_COORDINATES,
        name="declared_opengl",
        camera_axes="opengl",
        scale_class="metric",
        scale_to_meters=1.0,
    )

    converted = sceneio.convert_coordinates(
        unknown,
        source=declared,
        target=declared,
    )

    assert converted is not unknown
    assert converted.coordinate_frame == "opengl"
    np.testing.assert_array_equal(converted.positions, unknown.positions)

    recorded = _core.point_cloud(
        np.zeros((1, 3), dtype=np.float32),
        coordinate_frame="opencv",
    )
    mixed_source = replace(
        recorded.coordinates,
        name="mixed_source",
        world_frame="enu",
    )
    with pytest.raises(ValueError, match="combines camera axes"):
        sceneio.convert_coordinates(
            recorded,
            source=mixed_source,
            target=recorded.coordinates,
        )


@pytest.mark.parametrize("role", ["source", "target"])
def test_point_conversion_refuses_mixed_camera_and_named_world_frames(role):
    record = _core.point_cloud(
        np.zeros((1, 3), dtype=np.float32),
        coordinate_frame="opencv",
    )
    mixed = replace(
        record.coordinates,
        name="mixed_frame",
        world_frame="enu",
    )
    kwargs = (
        {"source": mixed, "target": sceneio.COLMAP_COORDINATES}
        if role == "source"
        else {"target": mixed}
    )

    with pytest.raises(ValueError, match="combines camera axes"):
        sceneio.convert_coordinates(
            record,
            world_transform=np.eye(4),
            **kwargs,
        )


def test_qualified_semantic_identity_returns_the_original_record():
    records = (
        _core.pose_storage(
            np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float64),
            np.zeros((1, 3), dtype=np.float64),
        ),
        _core.point_cloud(
            np.zeros((1, 3), dtype=np.float32),
            coordinate_frame="opencv",
        ),
        _core.gaussian_cloud(
            np.zeros((1, 3), dtype=np.float32),
            np.ones((1, 3), dtype=np.float32),
            np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32),
            np.zeros(1, dtype=np.float32),
            np.zeros((1, 3), dtype=np.float32),
        ),
        _core.mesh(
            np.zeros((3, 3), dtype=np.float32),
            np.array([0, 3], dtype=np.uint64),
            np.array([0, 1, 2], dtype=np.uint64),
            coordinate_frame="opencv",
        ),
    )
    for record in records:
        assert sceneio.convert_coordinates(record, target=record.coordinates) is record


def test_installed_wheel_smoke_checks_coordinate_contract_for_every_format(tmp_path):
    from sceneio import _wheel_smoke

    observations = _wheel_smoke._run_manifest_smoke(tmp_path)
    assert tuple(observations) == CANONICAL_BUILTIN_IDS
    assert all("coordinates" in properties for properties in observations.values())
