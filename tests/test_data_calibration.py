"""Validation tests for sceneio.data.calibration."""

from __future__ import annotations

import numpy as np
import pytest

from sceneio.data import Calibration, CameraIntrinsics, CameraModel, RayMap
from sceneio.errors import ContractViolation


def pinhole(width: int = 640, height: int = 480) -> CameraIntrinsics:
    return CameraIntrinsics(
        model=CameraModel.PINHOLE,
        width=width,
        height=height,
        params=np.array([500.0, 500.0, width / 2, height / 2]),
    )


def unit_rays(height: int = 4, width: int = 6) -> RayMap:
    directions = np.zeros((height, width, 3), dtype=np.float32)
    directions[..., 2] = 1.0
    return RayMap(directions=directions)


class TestCameraModel:
    def test_colmap_model_ids_are_stable(self) -> None:
        assert CameraModel.SIMPLE_PINHOLE.model_id == 0
        assert CameraModel.PINHOLE.model_id == 1
        assert CameraModel.THIN_PRISM_FISHEYE.model_id == 10
        assert len(CameraModel) == 11
        assert len({m.model_id for m in CameraModel}) == 11

    @pytest.mark.parametrize(
        ("model", "count"),
        [
            (CameraModel.SIMPLE_PINHOLE, 3),
            (CameraModel.PINHOLE, 4),
            (CameraModel.SIMPLE_RADIAL, 4),
            (CameraModel.RADIAL, 5),
            (CameraModel.OPENCV, 8),
            (CameraModel.OPENCV_FISHEYE, 8),
            (CameraModel.FULL_OPENCV, 12),
            (CameraModel.FOV, 5),
            (CameraModel.SIMPLE_RADIAL_FISHEYE, 4),
            (CameraModel.RADIAL_FISHEYE, 5),
            (CameraModel.THIN_PRISM_FISHEYE, 12),
        ],
    )
    def test_param_counts(self, model: CameraModel, count: int) -> None:
        assert model.num_params == count
        assert len(model.param_names) == count


class TestCameraIntrinsics:
    def test_valid_construction(self) -> None:
        cam = pinhole()
        assert cam.params.dtype == np.float64
        assert cam.params.shape == (4,)

    def test_model_accepts_string_name(self) -> None:
        cam = CameraIntrinsics(
            model="SIMPLE_PINHOLE", width=10, height=10, params=np.array([5.0, 5.0, 5.0])
        )
        assert cam.model is CameraModel.SIMPLE_PINHOLE

    def test_unknown_model_string_raises(self) -> None:
        with pytest.raises(ContractViolation, match="unknown camera model"):
            CameraIntrinsics(model="EQUIRECT", width=10, height=10, params=np.zeros(3))

    def test_non_model_type_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"CameraIntrinsics\.model"):
            CameraIntrinsics(model=1, width=10, height=10, params=np.zeros(4))  # type: ignore[arg-type]

    def test_wrong_param_count_raises(self) -> None:
        with pytest.raises(ContractViolation, match="PINHOLE takes 4 params"):
            CameraIntrinsics(model=CameraModel.PINHOLE, width=10, height=10, params=np.zeros(3))

    def test_param_count_message_names_params(self) -> None:
        with pytest.raises(ContractViolation, match=r"\('f', 'cx', 'cy'\)"):
            CameraIntrinsics(
                model=CameraModel.SIMPLE_PINHOLE, width=10, height=10, params=np.zeros(4)
            )

    def test_non_finite_params_raise(self) -> None:
        with pytest.raises(ContractViolation, match="non-finite"):
            CameraIntrinsics(
                model=CameraModel.SIMPLE_PINHOLE,
                width=10,
                height=10,
                params=np.array([np.nan, 5.0, 5.0]),
            )

    @pytest.mark.parametrize("bad", [0, -1, 1.5, "640", True])
    def test_bad_width_height_raise(self, bad: object) -> None:
        with pytest.raises(ContractViolation, match="positive int"):
            CameraIntrinsics(
                model=CameraModel.SIMPLE_PINHOLE,
                width=bad,
                height=10,
                params=np.zeros(3),  # type: ignore[arg-type]
            )
        with pytest.raises(ContractViolation, match="positive int"):
            CameraIntrinsics(
                model=CameraModel.SIMPLE_PINHOLE,
                width=10,
                height=bad,
                params=np.zeros(3),  # type: ignore[arg-type]
            )

    def test_params_bad_shape_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"CameraIntrinsics\.params"):
            CameraIntrinsics(
                model=CameraModel.PINHOLE, width=10, height=10, params=np.zeros((2, 2))
            )


class TestRayMap:
    def test_valid_unit_rays(self) -> None:
        rays = unit_rays()
        assert rays.height == 4
        assert rays.width == 6

    def test_float64_accepted(self) -> None:
        directions = np.zeros((2, 2, 3), dtype=np.float64)
        directions[..., 0] = 1.0
        RayMap(directions=directions)

    def test_wrong_dtype_raises(self) -> None:
        with pytest.raises(ContractViolation, match="dtype float32 or float64"):
            RayMap(directions=np.zeros((2, 2, 3), dtype=np.int32))

    def test_wrong_shape_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"RayMap\.directions"):
            RayMap(directions=np.zeros((2, 2, 2), dtype=np.float32))
        with pytest.raises(ContractViolation, match=r"RayMap\.directions"):
            RayMap(directions=np.zeros((2, 3), dtype=np.float32))

    def test_non_unit_rays_raise(self) -> None:
        directions = np.full((2, 2, 3), 0.9, dtype=np.float32)
        with pytest.raises(ContractViolation, match="unit-norm"):
            RayMap(directions=directions)

    def test_non_finite_rays_raise(self) -> None:
        directions = np.zeros((2, 2, 3), dtype=np.float32)
        directions[..., 2] = 1.0
        directions[0, 0, 2] = np.nan
        with pytest.raises(ContractViolation, match="non-finite"):
            RayMap(directions=directions)

    def test_not_an_array_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"expected numpy\.ndarray"):
            RayMap(directions=[[0.0, 0.0, 1.0]])  # type: ignore[arg-type]


class TestCalibration:
    def test_from_intrinsics(self) -> None:
        cal = Calibration.from_intrinsics(pinhole())
        assert cal.kind == "intrinsics"
        assert cal.image_size == (480, 640)

    def test_from_rays(self) -> None:
        cal = Calibration.from_rays(unit_rays(3, 5))
        assert cal.kind == "rays"
        assert cal.image_size == (3, 5)

    def test_neither_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"exactly one.*got neither"):
            Calibration()

    def test_both_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"exactly one.*got both"):
            Calibration(intrinsics=pinhole(), rays=unit_rays())

    def test_wrong_intrinsics_type_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"Calibration\.intrinsics"):
            Calibration(intrinsics="PINHOLE")  # type: ignore[arg-type]

    def test_wrong_rays_type_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"Calibration\.rays"):
            Calibration(rays=np.zeros((2, 2, 3), dtype=np.float32))  # type: ignore[arg-type]
