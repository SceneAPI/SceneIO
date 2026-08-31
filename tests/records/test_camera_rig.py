"""CameraRig lossless calibration contract, validation, and lifetime tests."""

from __future__ import annotations

import gc

import numpy as np
import pytest

import sceneio
from sceneio import _core


def _arrays(count: int = 3):
    camera_ids = np.arange(10, 10 + count, dtype=np.uint32)
    resolutions = np.tile(np.array([[640, 480]], np.uint64), (count, 1))
    projection_models = ["pinhole"] * count
    intrinsic_offsets = np.arange(count + 1, dtype=np.uint64) * 4
    intrinsics = np.arange(count * 4, dtype=np.float64) + 400.0
    distortion_models = ["radtan"] * count
    distortion_offsets = np.arange(count + 1, dtype=np.uint64) * 4
    distortion = np.arange(count * 4, dtype=np.float64) / 1000.0
    quaternions = np.zeros((count, 4), dtype=np.float64)
    quaternions[:, 0] = 1.0
    translations = np.arange(count * 3, dtype=np.float64).reshape(count, 3)
    return (
        camera_ids,
        resolutions,
        projection_models,
        intrinsic_offsets,
        intrinsics,
        distortion_models,
        distortion_offsets,
        distortion,
        quaternions,
        translations,
    )


def _make(count: int = 3, **kwargs):
    values = _arrays(count)
    optional = {
        "names": [f"cam{index}" for index in range(count)],
        "camera_matrices": np.tile(np.eye(3), (count, 1, 1)),
        "rectification_matrices": np.tile(np.eye(3), (count, 1, 1)),
        "projection_matrices": np.tile(
            np.concatenate((np.eye(3), np.zeros((3, 1))), axis=1),
            (count, 1, 1),
        ),
        "binning": np.zeros((count, 2), np.uint32),
        "roi": np.zeros((count, 4), np.uint32),
        "roi_do_rectify": np.zeros(count, np.uint8),
        "has_operational": np.ones(count, np.uint8),
        "topics": [f"/cam{index}/image_raw" for index in range(count)],
        "time_offsets": np.arange(count, dtype=np.float64) / 1000.0,
        "reference_frame": "imu",
    }
    optional.update(kwargs)
    return _core.camera_rig(*values, **optional)


def test_public_type_shapes_dtypes_and_metadata():
    rig = _make()
    assert isinstance(rig, sceneio.CameraRig)
    assert not hasattr(sceneio.io, "CameraRig")
    assert rig.num_cameras == 3
    assert rig.camera_ids.shape == (3,)
    assert rig.camera_ids.dtype == np.uint32
    assert rig.resolutions.shape == (3, 2)
    assert rig.resolutions.dtype == np.uint64
    assert rig.intrinsic_offsets.shape == (4,)
    assert rig.intrinsics.shape == (12,)
    assert rig.distortion_offsets.shape == (4,)
    assert rig.distortion_coefficients.shape == (12,)
    assert rig.quaternions.shape == (3, 4)
    assert rig.translations.shape == (3, 3)
    assert rig.camera_matrices.shape == (3, 3, 3)
    assert rig.rectification_matrices.shape == (3, 3, 3)
    assert rig.projection_matrices.shape == (3, 3, 4)
    assert rig.binning.shape == (3, 2)
    assert rig.roi.shape == (3, 4)
    assert rig.names == ["cam0", "cam1", "cam2"]
    assert rig.projection_models == ["pinhole"] * 3
    assert rig.distortion_models == ["radtan"] * 3
    assert rig.topics == ["/cam0/image_raw", "/cam1/image_raw", "/cam2/image_raw"]
    assert rig.quaternion_order == "wxyz"
    assert rig.quaternion_sign == "preserved"
    assert rig.transform_convention == "reference_to_camera"
    assert rig.axis_frame == "opencv"
    assert rig.reference_frame == "imu"
    assert rig.scale_to_meters == 1.0
    assert (
        rig.time_offset_convention
        == "reference_time = camera_time + time_offset_seconds"
    )
    assert "CameraRig cameras=3 imu->camera/opencv" in repr(rig)


def test_factory_copies_sources_and_views_keep_record_alive():
    values = list(_arrays())
    source_ids = values[0]
    source_intrinsics = values[4]
    rig = _core.camera_rig(*values)
    expected_ids = source_ids.copy()
    expected_intrinsics = source_intrinsics.copy()
    source_ids[:] = 0
    source_intrinsics[:] = 0
    np.testing.assert_array_equal(rig.camera_ids, expected_ids)
    np.testing.assert_array_equal(rig.intrinsics, expected_intrinsics)

    view = rig.intrinsics
    del rig
    gc.collect()
    np.testing.assert_array_equal(view, expected_intrinsics)


def test_empty_rig_has_non_null_views_and_roundtrips_factory():
    rig = _make(0)
    assert rig.num_cameras == 0
    assert rig.camera_ids.shape == (0,)
    assert rig.resolutions.shape == (0, 2)
    assert rig.camera_matrices.shape == (0, 3, 3)
    assert rig.projection_matrices.shape == (0, 3, 4)
    assert rig.intrinsic_offsets.tolist() == [0]
    assert rig.distortion_offsets.tolist() == [0]
    assert rig.camera_ids.__array_interface__["data"][0] != 0


def test_empty_rig_accepts_explicit_empty_optional_masks():
    rig = _make(
        0,
        has_extrinsics=np.empty(0, np.uint8),
        has_camera_matrix=np.empty(0, np.uint8),
        has_rectification=np.empty(0, np.uint8),
        has_projection_matrix=np.empty(0, np.uint8),
        roi_do_rectify=np.empty(0, np.uint8),
        has_operational=np.empty(0, np.uint8),
        has_time_offset=np.empty(0, np.uint8),
    )
    assert rig.num_cameras == 0


def test_optional_fields_preserve_absent_vs_present():
    values = _arrays(2)
    # Presence masks require canonical zero placeholders for absent values.
    matrices = np.tile(np.eye(3), (2, 1, 1))
    matrices[1] = 0
    projections = np.tile(
        np.concatenate((np.eye(3), np.zeros((3, 1))), axis=1),
        (2, 1, 1),
    )
    projections[1] = 0
    quaternions = values[8].copy()
    translations = values[9].copy()
    quaternions[1] = [1, 0, 0, 0]
    translations[1] = 0
    rig = _core.camera_rig(
        *values[:8],
        quaternions,
        translations,
        has_extrinsics=np.array([1, 0], np.uint8),
        camera_matrices=matrices,
        has_camera_matrix=np.array([1, 0], np.uint8),
        rectification_matrices=matrices,
        has_rectification=np.array([1, 0], np.uint8),
        projection_matrices=projections,
        has_projection_matrix=np.array([1, 0], np.uint8),
    )
    assert rig.has_extrinsics.tolist() == [1, 0]
    assert rig.has_camera_matrix.tolist() == [1, 0]
    assert rig.has_rectification.tolist() == [1, 0]
    assert rig.has_projection_matrix.tolist() == [1, 0]


def test_xyzw_absent_extrinsics_use_xyzw_identity():
    values = list(_arrays(1))
    values[8][0] = [0, 0, 0, 1]
    values[9][0] = 0
    rig = _core.camera_rig(
        *values,
        has_extrinsics=np.array([0], np.uint8),
        quaternion_order="xyzw",
    )
    assert rig.quaternions.tolist() == [[0.0, 0.0, 0.0, 1.0]]


@pytest.mark.parametrize(
    ("index", "replacement"),
    [
        (0, np.zeros((2, 1), np.uint32)),
        (1, np.zeros((2, 3), np.uint64)),
        (3, np.array([0, 4], np.uint64)),
        (4, np.zeros((2, 2), np.float64)),
        (6, np.array([0, 4], np.uint64)),
        (7, np.zeros((2, 2), np.float64)),
        (8, np.zeros((2, 3), np.float64)),
        (9, np.zeros((2, 4), np.float64)),
    ],
)
def test_factory_rejects_bad_required_shapes(index, replacement):
    values = list(_arrays(2))
    values[index] = replacement
    with pytest.raises(ValueError):
        _core.camera_rig(*values)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"names": ["same", "same"]},
        {"camera_matrices": np.zeros((2, 9))},
        {"rectification_matrices": np.zeros((2, 3, 4))},
        {"projection_matrices": np.zeros((2, 4, 3))},
        {"has_extrinsics": np.array([1, 2], np.uint8)},
        {"has_camera_matrix": np.zeros(2, np.uint8)},
        {"has_time_offset": np.zeros(2, np.uint8)},
        {"time_offsets": np.array([0.0, np.nan])},
        {"scale_to_meters": 0.0},
        {"reference_frame": "world"},
        {"names": ["bad\nname", "good"]},
        {"topics": ["good", "bad\0topic"]},
    ],
)
def test_factory_rejects_invalid_optional_fields(kwargs):
    with pytest.raises(ValueError):
        _make(2, **kwargs)


def test_factory_rejects_invalid_values_and_ragged_offsets():
    values = list(_arrays(2))
    values[0][1] = values[0][0]
    with pytest.raises(ValueError, match="ids"):
        _core.camera_rig(*values)

    values = list(_arrays(2))
    values[1][0, 0] = 0
    with pytest.raises(ValueError, match="resolutions"):
        _core.camera_rig(*values)

    values = list(_arrays(2))
    values[3] = np.array([0, 5, 4], np.uint64)
    with pytest.raises(ValueError, match="offset"):
        _core.camera_rig(*values)

    values = list(_arrays(2))
    values[4][0] = np.inf
    with pytest.raises(ValueError, match="finite"):
        _core.camera_rig(*values)

    values = list(_arrays(2))
    values[8][0] = 0
    with pytest.raises(ValueError, match="nonzero"):
        _core.camera_rig(*values)


def test_absent_payloads_require_canonical_placeholders():
    values = list(_arrays(1))
    with pytest.raises(ValueError, match="identity"):
        _core.camera_rig(
            *values,
            has_extrinsics=np.zeros(1, np.uint8),
        )

    matrix = np.ones((1, 3, 3))
    with pytest.raises(ValueError, match="zero"):
        _core.camera_rig(
            *values,
            camera_matrices=matrix,
            has_camera_matrix=np.zeros(1, np.uint8),
        )

    with pytest.raises(ValueError, match="zero"):
        _core.camera_rig(
            *values,
            binning=np.ones((1, 2), np.uint32),
        )

    with pytest.raises(ValueError, match="zero"):
        _core.camera_rig(
            *values,
            time_offsets=np.ones(1),
            has_time_offset=np.zeros(1, np.uint8),
        )


def test_roi_must_fit_resolution():
    with pytest.raises(ValueError, match="ROI"):
        _make(
            1,
            roi=np.array([[630, 0, 20, 10]], np.uint32),
        )


def test_declared_canonical_sign_is_enforced():
    values = list(_arrays(1))
    values[8][0, 0] = -1
    with pytest.raises(ValueError, match="canonical_positive_w"):
        _core.camera_rig(
            *values,
            quaternion_sign="canonical_positive_w",
        )


def test_numpy_dlpack_export_preserves_values():
    rig = _make()
    actual = np.from_dlpack(rig.intrinsics)
    np.testing.assert_array_equal(actual, _arrays()[4])
