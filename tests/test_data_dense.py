"""Validation tests for sceneapi_io.data.dense."""

from __future__ import annotations

import numpy as np
import pytest

from sceneapi_io.data import ConfidenceMap, DepthMap, Mask, Pointmap
from sceneapi_io.errors import ContractViolation


class TestDepthMap:
    def test_valid_without_mask(self) -> None:
        d = DepthMap(depth=np.ones((4, 5), dtype=np.float32))
        assert d.shape == (4, 5)
        assert d.valid is None

    def test_valid_with_mask_ignores_invalid_pixels(self) -> None:
        depth = np.full((2, 2), np.nan, dtype=np.float32)
        depth[0, 0] = 1.5
        valid = np.zeros((2, 2), dtype=bool)
        valid[0, 0] = True
        DepthMap(depth=depth, valid=valid)

    def test_wrong_dtype_raises(self) -> None:
        with pytest.raises(ContractViolation, match="expected dtype float32, got float64"):
            DepthMap(depth=np.ones((2, 2), dtype=np.float64))

    def test_wrong_ndim_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"DepthMap\.depth.*2-D"):
            DepthMap(depth=np.ones((2, 2, 1), dtype=np.float32))

    def test_mask_shape_mismatch_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"DepthMap\.valid"):
            DepthMap(
                depth=np.ones((2, 2), dtype=np.float32),
                valid=np.ones((3, 3), dtype=bool),
            )

    def test_mask_wrong_dtype_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"DepthMap\.valid.*dtype bool"):
            DepthMap(
                depth=np.ones((2, 2), dtype=np.float32),
                valid=np.ones((2, 2), dtype=np.uint8),
            )

    def test_nan_without_mask_raises(self) -> None:
        depth = np.ones((2, 2), dtype=np.float32)
        depth[0, 0] = np.nan
        with pytest.raises(ContractViolation, match="non-finite"):
            DepthMap(depth=depth)

    def test_nan_on_valid_pixel_raises(self) -> None:
        depth = np.full((2, 2), np.nan, dtype=np.float32)
        with pytest.raises(ContractViolation, match="non-finite"):
            DepthMap(depth=depth, valid=np.ones((2, 2), dtype=bool))

    @pytest.mark.parametrize("bad", [0.0, -1.0])
    def test_non_positive_valid_depth_raises(self, bad: float) -> None:
        depth = np.ones((2, 2), dtype=np.float32)
        depth[1, 1] = bad
        with pytest.raises(ContractViolation, match="must be > 0"):
            DepthMap(depth=depth)


class TestPointmap:
    def test_valid_default_world_frame(self) -> None:
        p = Pointmap(points=np.zeros((3, 4, 3), dtype=np.float32))
        assert p.frame == "world"
        assert p.shape == (3, 4)

    def test_camera_frame(self) -> None:
        p = Pointmap(points=np.zeros((2, 2, 3), dtype=np.float32), frame="camera")
        assert p.frame == "camera"

    def test_nan_pixels_allowed(self) -> None:
        points = np.full((2, 2, 3), np.nan, dtype=np.float32)
        Pointmap(points=points)

    def test_wrong_dtype_raises(self) -> None:
        with pytest.raises(ContractViolation, match="expected dtype float32"):
            Pointmap(points=np.zeros((2, 2, 3), dtype=np.float64))

    def test_wrong_last_dim_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"Pointmap\.points"):
            Pointmap(points=np.zeros((2, 2, 4), dtype=np.float32))

    def test_unknown_frame_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"Pointmap\.frame"):
            Pointmap(points=np.zeros((2, 2, 3), dtype=np.float32), frame="object")  # type: ignore[arg-type]


class TestConfidenceMap:
    def test_valid(self) -> None:
        c = ConfidenceMap(values=np.full((2, 3), 0.5, dtype=np.float32))
        assert c.shape == (2, 3)

    @pytest.mark.parametrize("bad", [-0.1, 1.5])
    def test_out_of_range_raises(self, bad: float) -> None:
        values = np.full((2, 2), bad, dtype=np.float32)
        with pytest.raises(ContractViolation, match=r"\[0, 1\]"):
            ConfidenceMap(values=values)

    def test_nan_raises(self) -> None:
        values = np.zeros((2, 2), dtype=np.float32)
        values[0, 0] = np.nan
        with pytest.raises(ContractViolation, match="non-finite"):
            ConfidenceMap(values=values)

    def test_wrong_dtype_raises(self) -> None:
        with pytest.raises(ContractViolation, match="expected dtype float32"):
            ConfidenceMap(values=np.zeros((2, 2), dtype=np.float64))

    def test_wrong_ndim_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"ConfidenceMap\.values"):
            ConfidenceMap(values=np.zeros((2,), dtype=np.float32))


class TestMask:
    def test_valid(self) -> None:
        m = Mask(mask=np.ones((2, 2), dtype=bool))
        assert m.shape == (2, 2)

    def test_wrong_dtype_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"Mask\.mask.*dtype bool"):
            Mask(mask=np.ones((2, 2), dtype=np.uint8))

    def test_wrong_ndim_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"Mask\.mask"):
            Mask(mask=np.ones((2, 2, 1), dtype=bool))

    def test_not_an_array_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"expected numpy\.ndarray"):
            Mask(mask=[[True, False]])  # type: ignore[arg-type]
