"""Coordinate contracts and explicit conversion verification."""

from __future__ import annotations

import dataclasses
import gc
import tomllib
from dataclasses import replace
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
        _core.posed_view_set(quaternions[..., None], translations)
    with pytest.raises(ValueError, match="timestamps"):
        _core.posed_view_set(
            quaternions,
            translations,
            timestamps=np.zeros((1, 1), dtype=np.float64),
        )
    with pytest.raises(ValueError, match="scale_to_meters"):
        _core.posed_view_set(
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


def test_extension_capability_uses_explicit_unspecified_fallback():
    codec = sceneio.io.Codec(
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
    mask = sceneio.data.Mask(np.zeros((2, 3), dtype=np.bool_))
    assert mask.coordinates == sceneio.IMAGE_COORDINATES

    features = sceneio.data.FeatureSet(
        np.array([[10.5, 20.5]], dtype=np.float32)
    )
    pairs = sceneio.data.PairCorrespondences.from_coordinates(
        np.array([[10.5, 20.5]], dtype=np.float32),
        np.array([[30.5, 40.5]], dtype=np.float32),
    )
    assert features.coordinates == sceneio.IMAGE_COORDINATES
    assert pairs.coordinates == sceneio.IMAGE_COORDINATES

    indexed = sceneio.data.PairCorrespondences.from_indices(
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

    hloc_graph = sceneio.data.CorrespondenceGraph(
        features={
            "a": sceneio.data.FeatureSet(
                np.array([[10.0, 20.0]], dtype=np.float32),
                pixel_center=(0.0, 0.0),
            ),
            "b": sceneio.data.FeatureSet(
                np.array([[30.0, 40.0]], dtype=np.float32),
                pixel_center=(0.0, 0.0),
            ),
        },
        pairs={("a", "b"): indexed},
    )
    assert hloc_graph.coordinates.pixel_center == (0.0, 0.0)

    frame = sceneio.data.FrameMeta(
        world_frame="capture_rig",
        scale="metric",
        scale_provenance="prior_anchored",
    )
    assert frame.coordinates.world_frame == "reference"
    assert frame.coordinates.reference_frame == "capture_rig"
    assert frame.coordinates.scale_to_meters == 1.0

    tracked = sceneio.data.TrackedPointCloud(
        np.zeros((1, 3), dtype=np.float32),
        tracks=((sceneio.data.TrackObservation("image", 0),),),
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
    camera = _core.camera(
        7,
        1,
        640,
        480,
        np.array([500.0, 510.0, 320.5, 240.5], dtype=np.float64),
    )
    source = _core.posed_view_set(
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
    assert converted.cameras[0].id == 7

    camera_center = -actual_w2c[:3, :3].T @ actual_w2c[:3, 3]
    np.testing.assert_allclose(camera_center, source_c2w[:3, 3])

    del source, camera
    gc.collect()
    np.testing.assert_allclose(converted.translations, expected_w2c[:3, 3][None])
    assert converted.cameras[0].id == 7


def test_pose_conversion_round_trip_is_geometrically_exact():
    source = _core.posed_view_set(
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

    xyzw_source = _core.posed_view_set(
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

    views = _core.posed_view_set(
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
    gaussian = _core.gaussian_cloud(
        np.zeros((1, 3), dtype=np.float32),
        np.ones((1, 3), dtype=np.float32),
        np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32),
        np.zeros(1, dtype=np.float32),
        np.zeros((1, 3), dtype=np.float32),
    )
    with pytest.raises(TypeError, match="not qualified"):
        sceneio.convert_coordinates(
            gaussian,
            source=replace(
                sceneio.COLMAP_COORDINATES,
                name="declared_gaussian_source",
                camera_axes="opengl",
            ),
        )

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


def test_installed_wheel_smoke_checks_coordinate_contract_for_every_format(tmp_path):
    from sceneio import _wheel_smoke

    observations = _wheel_smoke._run_manifest_smoke(tmp_path)
    assert tuple(observations) == CANONICAL_BUILTIN_IDS
    assert all("coordinates" in properties for properties in observations.values())
