"""Canonical camera authority and native/neutral adapter tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import sceneio
import sceneio.colmap.mapping_input as colmap_mapping_input
import sceneio.colmap.models as colmap_models
import sceneio.colmap.rig as colmap_rig
import sceneio.colmap.sparse as colmap_sparse
from sceneio import _core
from sceneio._camera_models import (
    CAMERA_MODEL_PARAMETER_COUNTS,
    CAMERA_MODEL_PARAMETER_COUNTS_BY_NAME,
    CAMERA_MODEL_SPECS,
)
from sceneio.canonical import (
    camera_from_neutral,
    camera_intrinsics_from_native,
    correspondence_graph_from_native,
    depth_map_from_native,
    depth_map_from_neutral,
    feature_set_from_native,
    feature_set_from_neutral,
    match_graph_from_neutral,
    posed_view_set_from_native,
    posed_view_set_from_neutral,
)
from sceneio.data import (
    SE3,
    Calibration,
    CameraIntrinsics,
    CameraModel,
    CorrespondenceGraph,
    DepthMap,
    FeatureSet,
    FrameMeta,
    Mask,
    PairCorrespondences,
    PosedViewSet,
    TwoViewGeometry,
    ViewInput,
)
from sceneio.errors import ContractViolation

ROOT = Path(__file__).resolve().parents[1]


def _features() -> FeatureSet:
    return FeatureSet(
        np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32),
        np.arange(6, dtype=np.float32).reshape(2, 3),
        np.array([0.25, 0.75], dtype=np.float32),
    )


def _intrinsics() -> CameraIntrinsics:
    return CameraIntrinsics(
        CameraModel.PINHOLE,
        6,
        4,
        np.array([4.0, 4.0, 3.0, 2.0], dtype=np.float64),
    )


def test_camera_manifest_is_the_python_and_native_authority(tmp_path: Path) -> None:
    assert colmap_models._CAMERA_PARAMETER_COUNTS is CAMERA_MODEL_PARAMETER_COUNTS
    assert colmap_models._CAMERA_PARAMETER_COUNTS_BY_NAME is CAMERA_MODEL_PARAMETER_COUNTS_BY_NAME
    assert colmap_mapping_input._CAMERA_PARAM_COUNTS is CAMERA_MODEL_PARAMETER_COUNTS
    assert colmap_rig._MODEL_PARAM_COUNTS is CAMERA_MODEL_PARAMETER_COUNTS_BY_NAME
    assert colmap_sparse._CAMERA_PARAM_COUNTS is CAMERA_MODEL_PARAMETER_COUNTS

    assert tuple((model.model_id, model.value, model.param_names) for model in CameraModel) == (
        CAMERA_MODEL_SPECS
    )
    for model_id, name, params in CAMERA_MODEL_SPECS:
        native = _core.camera(
            model_id + 1,
            model_id,
            640,
            480,
            np.zeros(len(params), dtype=np.float64),
        )
        assert native.model == name
        with pytest.raises(ValueError, match="params length"):
            _core.camera(
                model_id + 1,
                model_id,
                640,
                480,
                np.zeros(len(params) + 1, dtype=np.float64),
            )

    generated = tmp_path / "camera_models.hpp"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "generate_camera_models.py"),
            "--manifest",
            str(ROOT / "src" / "sceneio" / "_camera_models.py"),
            "--output",
            str(generated),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    text = generated.read_text(encoding="utf-8")
    for model_id, name, params in CAMERA_MODEL_SPECS:
        assert f'case {model_id}: return {{"{name}", {len(params)}}};' in text


def test_camera_adapter_round_trips_every_model() -> None:
    for model in CameraModel:
        intrinsics = CameraIntrinsics(
            model,
            640,
            480,
            np.arange(model.num_params, dtype=np.float64),
        )
        native = camera_from_neutral(intrinsics, camera_id=model.model_id + 10)
        recovered = camera_intrinsics_from_native(native)
        assert recovered.model is model
        assert (recovered.height, recovered.width) == (480, 640)
        np.testing.assert_array_equal(recovered.params, intrinsics.params)


def test_feature_adapter_exact_subset_and_explicit_loss() -> None:
    neutral = _features()
    native = feature_set_from_neutral(neutral)
    recovered = feature_set_from_native(native)
    np.testing.assert_array_equal(recovered.keypoints, neutral.keypoints)
    np.testing.assert_array_equal(recovered.descriptors, neutral.descriptors)
    np.testing.assert_array_equal(recovered.scores, neutral.scores)

    contextual = feature_set_from_neutral(
        neutral,
        image_id=7,
        image_name="images/a.jpg",
        camera_id=3,
        image_size=(6, 4),
    )
    with pytest.raises(ContractViolation, match="image_id"):
        feature_set_from_native(contextual)
    projected = feature_set_from_native(contextual, allow_loss=True)
    np.testing.assert_array_equal(projected.keypoints, neutral.keypoints)

    affine = _core.feature_set(np.zeros((2, 6), dtype=np.float32))
    with pytest.raises(ContractViolation, match="affine columns"):
        feature_set_from_native(affine)
    assert feature_set_from_native(affine, allow_loss=True).keypoints.shape == (2, 2)


def test_feature_adapter_refuses_native_unsupported_descriptor_dtype() -> None:
    neutral = FeatureSet(
        np.zeros((1, 2), dtype=np.float32),
        np.zeros((1, 2), dtype=np.int16),
    )
    with pytest.raises(ContractViolation, match="descriptors require"):
        feature_set_from_neutral(neutral)


def test_match_adapter_round_trips_shared_raw_subset() -> None:
    features = {"a.jpg": _features(), "b.jpg": _features()}
    pair = PairCorrespondences.from_indices(
        np.array([[0, 1], [1, 0]], dtype=np.uint32),
        scores=np.array([0.8, 0.6], dtype=np.float32),
        geometry=TwoViewGeometry(F=np.eye(3, dtype=np.float64)),
    )
    neutral = CorrespondenceGraph(features, {("a.jpg", "b.jpg"): pair})
    native = match_graph_from_neutral(
        neutral,
        image_ids={"a.jpg": 2, "b.jpg": 11},
    )
    native_features = {
        name: feature_set_from_neutral(feature) for name, feature in features.items()
    }
    recovered = correspondence_graph_from_native(
        native,
        native_features,
        image_names={2: "a.jpg", 11: "b.jpg"},
    )
    recovered_pair = recovered.pairs[("a.jpg", "b.jpg")]
    np.testing.assert_array_equal(recovered_pair.indices, pair.indices)
    np.testing.assert_array_equal(recovered_pair.scores, pair.scores)
    assert recovered_pair.geometry is not None
    np.testing.assert_array_equal(recovered_pair.geometry.F, pair.geometry.F)


def test_match_adapter_requires_channel_and_loss_acknowledgement() -> None:
    native = _core.match_graph(
        np.array([[1, 2]], dtype=np.uint32),
        np.array([0, 1], dtype=np.uint64),
        np.array([[0, 0]], dtype=np.uint32),
        np.array([0, 1], dtype=np.uint64),
        np.array([[1, 1]], dtype=np.uint32),
        match_present=np.array([1], dtype=np.uint8),
        geometry_present=np.array([1], dtype=np.uint8),
    )
    features = {
        "a": feature_set_from_neutral(_features()),
        "b": feature_set_from_neutral(_features()),
    }
    with pytest.raises(ContractViolation, match="verified correspondences"):
        correspondence_graph_from_native(
            native,
            features,
            image_names=("a", "b"),
            channel="raw",
        )
    raw = correspondence_graph_from_native(
        native,
        features,
        image_names=("a", "b"),
        channel="raw",
        allow_loss=True,
    )
    np.testing.assert_array_equal(raw.pairs[("a", "b")].indices, [[0, 0]])

    verified = CorrespondenceGraph(
        {"a": _features(), "b": _features()},
        {
            ("a", "b"): PairCorrespondences.from_indices(
                np.array([[0, 0]], dtype=np.uint32),
                scores=np.array([0.5], dtype=np.float32),
            )
        },
    )
    with pytest.raises(ContractViolation, match="scores for verified"):
        match_graph_from_neutral(
            verified,
            image_ids={"a": 1, "b": 2},
            channel="verified",
        )


def test_match_adapter_uses_the_selected_channel_presence_flag() -> None:
    native_features = {
        "a": feature_set_from_neutral(_features()),
        "b": feature_set_from_neutral(_features()),
    }
    geometry_only = _core.match_graph(
        np.array([[1, 2]], dtype=np.uint32),
        np.array([0, 0], dtype=np.uint64),
        np.empty((0, 2), dtype=np.uint32),
        np.array([0, 1], dtype=np.uint64),
        np.array([[0, 0]], dtype=np.uint32),
        match_present=np.array([0], dtype=np.uint8),
        geometry_present=np.array([1], dtype=np.uint8),
    )
    verified = correspondence_graph_from_native(
        geometry_only,
        native_features,
        image_names=("a", "b"),
        channel="verified",
    )
    verified_pair = verified.pairs[("a", "b")]
    np.testing.assert_array_equal(verified_pair.indices, [[0, 0]])
    assert verified_pair.geometry is not None
    assert verified_pair.geometry.num_inliers == 1

    raw_only_empty = _core.match_graph(
        np.array([[1, 2]], dtype=np.uint32),
        np.array([0, 0], dtype=np.uint64),
        np.empty((0, 2), dtype=np.uint32),
        np.array([0, 0], dtype=np.uint64),
        np.empty((0, 2), dtype=np.uint32),
        match_present=np.array([1], dtype=np.uint8),
        geometry_present=np.array([0], dtype=np.uint8),
    )
    with pytest.raises(ContractViolation, match="absent-versus-empty match rows"):
        correspondence_graph_from_native(
            raw_only_empty,
            native_features,
            image_names=("a", "b"),
            channel="verified",
        )
    acknowledged = correspondence_graph_from_native(
        raw_only_empty,
        native_features,
        image_names=("a", "b"),
        channel="verified",
        allow_loss=True,
    )
    assert acknowledged.pairs[("a", "b")].indices.shape == (0, 2)


def test_match_adapter_materializes_verified_rows_without_matrices() -> None:
    neutral = CorrespondenceGraph(
        {"a": _features(), "b": _features()},
        {("a", "b"): PairCorrespondences.from_indices(np.array([[0, 0]], dtype=np.uint32))},
    )
    native = match_graph_from_neutral(
        neutral,
        image_ids={"a": 1, "b": 2},
        channel="verified",
    )
    np.testing.assert_array_equal(native.match_present, [0])
    np.testing.assert_array_equal(native.geometry_present, [1])
    assert native.num_verified_matches == 1

    recovered = correspondence_graph_from_native(
        native,
        {name: feature_set_from_neutral(value) for name, value in neutral.features.items()},
        image_names=("a", "b"),
        channel="verified",
    )
    recovered_pair = recovered.pairs[("a", "b")]
    np.testing.assert_array_equal(recovered_pair.indices, [[0, 0]])
    assert recovered_pair.geometry is not None
    assert recovered_pair.geometry.num_inliers == 1

    raw_with_empty_geometry = CorrespondenceGraph(
        neutral.features,
        {
            ("a", "b"): PairCorrespondences.from_indices(
                np.array([[0, 0]], dtype=np.uint32),
                geometry=TwoViewGeometry(),
            )
        },
    )
    raw_native = match_graph_from_neutral(
        raw_with_empty_geometry,
        image_ids={"a": 1, "b": 2},
        channel="raw",
    )
    np.testing.assert_array_equal(raw_native.geometry_present, [1])


def test_match_adapter_refuses_coordinate_pairs_and_reversed_native_ids() -> None:
    coordinate_pair = PairCorrespondences.from_coordinates(
        np.zeros((1, 2), dtype=np.float32),
        np.ones((1, 2), dtype=np.float32),
    )
    coordinate_graph = CorrespondenceGraph({}, {("a", "b"): coordinate_pair})
    with pytest.raises(ContractViolation, match="coordinate-mode"):
        match_graph_from_neutral(coordinate_graph, image_ids={"a": 1, "b": 2})

    indexed = CorrespondenceGraph(
        {"a": _features(), "b": _features()},
        {("a", "b"): PairCorrespondences.from_indices(np.array([[0, 0]], dtype=np.uint32))},
    )
    with pytest.raises(ContractViolation, match="must increase"):
        match_graph_from_neutral(indexed, image_ids={"a": 2, "b": 1})


def test_depth_adapter_converts_units_and_encodes_validity() -> None:
    native = _core.depth_map(
        np.array([[1000.0, 0.0]], dtype=np.float32),
        unit="millimeters",
        invalid_policy="nonpositive",
        depth_convention="camera_z",
    )
    neutral = depth_map_from_native(native, scale_to_parent_units=0.001)
    np.testing.assert_allclose(neutral.depth, [[1.0, 0.0]])
    np.testing.assert_array_equal(neutral.valid, [[True, False]])

    restored = depth_map_from_neutral(
        neutral,
        unit="meters",
        invalid_policy="nonfinite",
    )
    assert np.isnan(restored.depth[0, 1])
    assert restored.depth[0, 0] == 1.0


def test_depth_adapter_refuses_implicit_semantic_loss() -> None:
    values = np.ones((2, 2), dtype=np.float32)
    confidence = np.ones((2, 2), dtype=np.float32)
    native = _core.depth_map(
        values,
        confidence=confidence,
        depth_convention="camera_z",
    )
    with pytest.raises(ContractViolation, match="confidence raster"):
        depth_map_from_native(native, scale_to_parent_units=1.0)
    depth_map_from_native(native, scale_to_parent_units=1.0, allow_loss=True)

    unspecified = _core.depth_map(values, depth_convention="unspecified")
    with pytest.raises(ContractViolation, match="unspecified depth convention"):
        depth_map_from_native(unspecified, scale_to_parent_units=1.0)
    ray_distance = _core.depth_map(values, depth_convention="ray_distance")
    with pytest.raises(ContractViolation, match="ray calibration"):
        depth_map_from_native(ray_distance, scale_to_parent_units=1.0, allow_loss=True)

    masked = DepthMap(values, np.array([[True, False], [True, True]], dtype=np.bool_))
    with pytest.raises(ContractViolation, match="cannot encode"):
        depth_map_from_neutral(masked, unit="meters", invalid_policy="none")

    with pytest.raises(ContractViolation, match="ray calibration"):
        depth_map_from_neutral(
            DepthMap(values),
            unit="meters",
            depth_convention="ray_distance",
        )
    with pytest.raises(ContractViolation, match="requires depth_convention='camera_z'"):
        depth_map_from_neutral(
            DepthMap(values),
            unit="meters",
            depth_convention="unspecified",
        )


def test_posed_view_adapter_round_trips_metric_pose_and_calibration() -> None:
    image = np.zeros((4, 6, 3), dtype=np.uint8)
    view = ViewInput(
        image,
        name="images/a.png",
        calibration=Calibration.from_intrinsics(_intrinsics()),
    )
    neutral = PosedViewSet(
        (view,),
        (SE3(np.eye(3), np.array([1.0, 2.0, 3.0])),),
        FrameMeta(world_frame="arbitrary", scale="metric"),
    )
    native = posed_view_set_from_neutral(
        neutral,
        scale_to_meters=0.001,
        quaternion_order="xyzw",
        pose_convention="camera_to_world",
        axis_frame="opengl",
    )
    assert native.quaternion_order == "xyzw"
    assert native.axis_frame == "opengl"
    recovered = posed_view_set_from_native(
        native,
        images=(image,),
        frame=neutral.frame,
    )
    assert recovered.views[0].name == "images/a.png"
    assert recovered.views[0].calibration is not None
    assert recovered.views[0].calibration.intrinsics.model is CameraModel.PINHOLE
    np.testing.assert_allclose(recovered.poses[0].matrix, neutral.poses[0].matrix, atol=1e-12)

    shared_calibration = PosedViewSet(
        (
            view,
            ViewInput(
                image,
                name="images/b.png",
                calibration=Calibration.from_intrinsics(_intrinsics()),
            ),
        ),
        (SE3.identity(), SE3.identity()),
        neutral.frame,
    )
    shared_native = posed_view_set_from_neutral(shared_calibration)
    assert len(shared_native.cameras) == 1
    np.testing.assert_array_equal(shared_native.camera_indices, [0, 0])


def test_posed_view_adapter_refuses_unrepresented_context() -> None:
    image = np.zeros((4, 6, 3), dtype=np.uint8)
    masked_view = ViewInput(image, mask=Mask(np.ones((4, 6), dtype=np.bool_)))
    neutral = PosedViewSet(
        (masked_view,),
        (SE3.identity(),),
        FrameMeta(world_frame="arbitrary", scale="metric"),
    )
    with pytest.raises(ContractViolation, match="mask for view"):
        posed_view_set_from_neutral(neutral)

    native = _core.posed_view_set(
        np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float64),
        np.zeros((1, 3), dtype=np.float64),
        timestamps=np.array([1.25], dtype=np.float64),
    )
    with pytest.raises(ContractViolation, match="timestamps"):
        posed_view_set_from_native(
            native,
            images=(image,),
            frame=FrameMeta(world_frame="arbitrary", scale="metric"),
        )


def test_posed_view_adapter_requires_explicit_scale_conversion() -> None:
    image = np.zeros((4, 6, 3), dtype=np.uint8)
    pose = SE3(np.eye(3), np.array([2.0, 0.0, 0.0]))
    for scale_class in ("arbitrary", "normalized"):
        neutral = PosedViewSet(
            (ViewInput(image),),
            (pose,),
            FrameMeta(world_frame="arbitrary", scale=scale_class),
        )
        with pytest.raises(ContractViolation, match="source_scale_to_meters"):
            posed_view_set_from_neutral(neutral)

    normalized = PosedViewSet(
        (ViewInput(image),),
        (pose,),
        FrameMeta(world_frame="arbitrary", scale="normalized"),
    )
    native = posed_view_set_from_neutral(
        normalized,
        source_scale_to_meters=0.5,
        scale_to_meters=0.25,
    )
    assert native.scale_to_meters == 0.25
    assert native.coordinates.scale_class == "metric"
    np.testing.assert_allclose(native.translations, [[4.0, 0.0, 0.0]], atol=1e-12)

    with pytest.raises(ContractViolation, match="normalization_scale_to_meters"):
        posed_view_set_from_native(
            native,
            images=(image,),
            frame=normalized.frame,
            allow_loss=True,
        )
    with pytest.raises(ContractViolation, match="native metric scale"):
        posed_view_set_from_native(
            native,
            images=(image,),
            frame=normalized.frame,
            normalization_scale_to_meters=0.5,
        )
    recovered = posed_view_set_from_native(
        native,
        images=(image,),
        frame=normalized.frame,
        normalization_scale_to_meters=0.5,
        allow_loss=True,
    )
    np.testing.assert_allclose(recovered.poses[0].matrix, pose.matrix, atol=1e-12)


def test_posed_view_adapter_accounts_for_unreferenced_cameras() -> None:
    image = np.zeros((4, 6, 3), dtype=np.uint8)
    first = _core.camera(
        1,
        CameraModel.PINHOLE.model_id,
        6,
        4,
        np.array([4.0, 4.0, 3.0, 2.0], dtype=np.float64),
    )
    unused = _core.camera(
        2,
        CameraModel.PINHOLE.model_id,
        6,
        4,
        np.array([5.0, 5.0, 3.0, 2.0], dtype=np.float64),
    )
    native = _core.posed_view_set(
        np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float64),
        np.zeros((1, 3), dtype=np.float64),
        camera_indices=np.array([0], dtype=np.int32),
        cameras=(first, unused),
    )
    frame = FrameMeta(world_frame="arbitrary", scale="metric")
    with pytest.raises(ContractViolation, match="unreferenced cameras"):
        posed_view_set_from_native(native, images=(image,), frame=frame)

    recovered = posed_view_set_from_native(
        native,
        images=(image,),
        frame=frame,
        allow_loss=True,
    )
    assert recovered.views[0].calibration is not None
    np.testing.assert_array_equal(
        recovered.views[0].calibration.intrinsics.params,
        first.params,
    )


def test_same_short_names_keep_distinct_roles() -> None:
    assert sceneio.DepthMap is not sceneio.data.DepthMap
    assert sceneio.FeatureSet is not sceneio.data.FeatureSet
    assert sceneio.PosedViewSet is not sceneio.data.PosedViewSet
