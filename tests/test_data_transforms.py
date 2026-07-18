"""Validation + conversion tests for sceneapi_io.data.transforms."""

from __future__ import annotations

import numpy as np
import pytest

from sceneapi_io.data import DEFAULT_CONVENTION, POSE_CONVENTIONS, SE3, Sim3
from sceneapi_io.errors import ContractViolation, SceneIoError


def _rot_z(angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


class TestSE3:
    def test_identity_and_matrix(self) -> None:
        pose = SE3.identity()
        assert pose.convention == DEFAULT_CONVENTION == "opencv_cam2world"
        np.testing.assert_allclose(pose.matrix, np.eye(4))

    def test_accepts_nested_lists_and_coerces_float64(self) -> None:
        pose = SE3([[1, 0, 0], [0, 1, 0], [0, 0, 1]], [1, 2, 3])
        assert pose.rotation.dtype == np.float64
        assert pose.translation.dtype == np.float64

    def test_rotation_bad_shape_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"SE3\.rotation.*shape"):
            SE3(np.eye(4), np.zeros(3))

    def test_translation_bad_shape_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"SE3\.translation.*shape"):
            SE3(np.eye(3), np.zeros(4))

    def test_non_numeric_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"SE3\.rotation"):
            SE3(object(), np.zeros(3))

    def test_non_finite_raises(self) -> None:
        bad = np.eye(3)
        bad[0, 0] = np.nan
        with pytest.raises(ContractViolation, match="non-finite"):
            SE3(bad, np.zeros(3))
        with pytest.raises(ContractViolation, match="non-finite"):
            SE3(np.eye(3), np.array([np.inf, 0.0, 0.0]))

    def test_non_orthonormal_rotation_raises(self) -> None:
        with pytest.raises(ContractViolation, match="not orthonormal"):
            SE3(np.eye(3) * 2.0, np.zeros(3))

    def test_reflection_raises(self) -> None:
        reflection = np.diag([1.0, 1.0, -1.0])
        with pytest.raises(ContractViolation, match="not a proper rotation"):
            SE3(reflection, np.zeros(3))

    def test_unknown_convention_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"SE3\.convention"):
            SE3(np.eye(3), np.zeros(3), convention="ros_cam2world")

    def test_conventions_vocabulary(self) -> None:
        assert {"opencv_cam2world", "opencv_world2cam"} == POSE_CONVENTIONS

    def test_inverse_flips_convention_and_roundtrips(self) -> None:
        pose = SE3(_rot_z(0.3), np.array([1.0, -2.0, 3.0]))
        inv = pose.inverse()
        assert inv.convention == "opencv_world2cam"
        np.testing.assert_allclose(inv.matrix @ pose.matrix, np.eye(4), atol=1e-12)
        back = inv.inverse()
        assert back.convention == pose.convention
        np.testing.assert_allclose(back.matrix, pose.matrix, atol=1e-12)

    def test_as_convention_same_is_noop(self) -> None:
        pose = SE3.identity()
        assert pose.as_convention("opencv_cam2world") is pose

    def test_as_convention_flip_inverts(self) -> None:
        pose = SE3(_rot_z(1.0), np.array([0.5, 0.0, 0.0]))
        flipped = pose.as_convention("opencv_world2cam")
        np.testing.assert_allclose(flipped.matrix, np.linalg.inv(pose.matrix), atol=1e-12)

    def test_as_convention_unknown_raises(self) -> None:
        with pytest.raises(ContractViolation, match="as_convention"):
            SE3.identity().as_convention("nerf")

    def test_colmap_roundtrip(self) -> None:
        rng = np.random.default_rng(7)
        axis = rng.normal(size=3)
        axis /= np.linalg.norm(axis)
        angle = 0.9
        w = np.cos(angle / 2)
        xyz = np.sin(angle / 2) * axis
        qvec = np.array([w, *xyz])
        tvec = np.array([0.1, -0.2, 0.3])
        pose = SE3.from_colmap_world2cam(qvec, tvec)
        assert pose.convention == "opencv_cam2world"
        q_back, t_back = pose.to_colmap_world2cam()
        np.testing.assert_allclose(q_back, qvec, atol=1e-12)
        np.testing.assert_allclose(t_back, tvec, atol=1e-12)

    def test_from_colmap_identity_semantics(self) -> None:
        # world2cam identity => cam2world identity
        pose = SE3.from_colmap_world2cam([1.0, 0.0, 0.0, 0.0], [1.0, 2.0, 3.0])
        # cam2world translation is the camera center: -R.T @ t
        np.testing.assert_allclose(pose.translation, [-1.0, -2.0, -3.0])

    def test_from_colmap_world2cam_convention_kwarg(self) -> None:
        pose = SE3.from_colmap_world2cam(
            [1.0, 0.0, 0.0, 0.0], [1.0, 2.0, 3.0], convention="opencv_world2cam"
        )
        assert pose.convention == "opencv_world2cam"
        np.testing.assert_allclose(pose.translation, [1.0, 2.0, 3.0])

    def test_from_colmap_non_unit_quaternion_raises(self) -> None:
        with pytest.raises(ContractViolation, match="unit-norm"):
            SE3.from_colmap_world2cam([2.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0])

    def test_from_colmap_bad_shapes_raise(self) -> None:
        with pytest.raises(ContractViolation, match="qvec_wxyz"):
            SE3.from_colmap_world2cam([1.0, 0.0, 0.0], [0.0, 0.0, 0.0])
        with pytest.raises(ContractViolation, match="tvec"):
            SE3.from_colmap_world2cam([1.0, 0.0, 0.0, 0.0], [0.0, 0.0])

    def test_to_colmap_quaternion_sign_normalized(self) -> None:
        pose = SE3(_rot_z(2.5), np.zeros(3))
        q, _ = pose.to_colmap_world2cam()
        assert q[0] >= 0
        np.testing.assert_allclose(np.linalg.norm(q), 1.0, atol=1e-12)

    def test_contract_violation_is_sceneio_error(self) -> None:
        assert issubclass(ContractViolation, SceneIoError)

    def test_frozen(self) -> None:
        pose = SE3.identity()
        with pytest.raises(AttributeError):
            pose.convention = "opencv_world2cam"  # type: ignore[misc]


class TestSim3:
    def test_identity(self) -> None:
        s = Sim3.identity()
        assert s.scale == 1.0
        np.testing.assert_allclose(s.matrix, np.eye(4))

    def test_matrix_scales_rotation_block(self) -> None:
        s = Sim3(2.0, np.eye(3), np.array([1.0, 0.0, 0.0]))
        np.testing.assert_allclose(s.matrix[:3, :3], 2.0 * np.eye(3))

    def test_inverse_roundtrips_and_flips(self) -> None:
        s = Sim3(0.5, _rot_z(-0.7), np.array([1.0, 2.0, -1.0]))
        inv = s.inverse()
        assert inv.convention == "opencv_world2cam"
        np.testing.assert_allclose(inv.matrix @ s.matrix, np.eye(4), atol=1e-12)

    @pytest.mark.parametrize("scale", [0.0, -1.0, float("nan"), float("inf")])
    def test_bad_scale_raises(self, scale: float) -> None:
        with pytest.raises(ContractViolation, match=r"Sim3\.scale"):
            Sim3(scale, np.eye(3), np.zeros(3))

    def test_non_numeric_scale_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"Sim3\.scale"):
            Sim3("2.0", np.eye(3), np.zeros(3))  # type: ignore[arg-type]

    def test_bool_scale_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"Sim3\.scale"):
            Sim3(True, np.eye(3), np.zeros(3))

    def test_non_orthonormal_rotation_raises(self) -> None:
        with pytest.raises(ContractViolation, match="not orthonormal"):
            Sim3(1.0, np.ones((3, 3)), np.zeros(3))

    def test_unknown_convention_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"Sim3\.convention"):
            Sim3(1.0, np.eye(3), np.zeros(3), convention="blender")

    def test_from_se3(self) -> None:
        pose = SE3(_rot_z(0.2), np.array([1.0, 1.0, 1.0]))
        s = Sim3.from_se3(pose, scale=3.0)
        assert s.scale == 3.0
        assert s.convention == pose.convention
        np.testing.assert_allclose(s.rotation, pose.rotation)
