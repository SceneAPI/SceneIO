"""Validation tests for sceneapi_io.data.views (+ FrameMeta)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sceneapi_io.data import (
    SE3,
    Calibration,
    CameraIntrinsics,
    CameraModel,
    DepthMap,
    FrameMeta,
    Mask,
    PosedViewSet,
    PosePrior,
    RayMap,
    ViewInput,
)
from sceneapi_io.errors import ContractViolation
from sceneapi_io.imagesource import MaterializedImage


def rgb(h: int = 4, w: int = 6) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def intrinsics(w: int, h: int) -> Calibration:
    return Calibration.from_intrinsics(
        CameraIntrinsics(
            model=CameraModel.SIMPLE_PINHOLE,
            width=w,
            height=h,
            params=np.array([float(w), w / 2, h / 2]),
        )
    )


class TestFrameMeta:
    def test_defaults(self) -> None:
        meta = FrameMeta()
        assert meta.world_frame == "first_view"
        assert meta.scale == "arbitrary"
        assert meta.scale_provenance == "unknown"

    def test_metric_prior_anchored(self) -> None:
        FrameMeta(scale="metric", scale_provenance="prior_anchored")

    def test_unknown_scale_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"FrameMeta\.scale"):
            FrameMeta(scale="meters")  # type: ignore[arg-type]

    def test_unknown_provenance_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"FrameMeta\.scale_provenance"):
            FrameMeta(scale_provenance="gut_feeling")  # type: ignore[arg-type]

    def test_empty_world_frame_raises(self) -> None:
        with pytest.raises(ContractViolation, match="world_frame"):
            FrameMeta(world_frame="")


class TestViewInput:
    def test_in_memory_rgb(self) -> None:
        view = ViewInput(image=rgb(), name="v0")
        assert view.ref == "v0"

    def test_in_memory_gray(self) -> None:
        ViewInput(image=np.zeros((4, 6), dtype=np.uint8))

    def test_materialized_image_ref(self) -> None:
        img = MaterializedImage(name="frame0.jpg", abs_path=Path("frame0.jpg"))
        view = ViewInput(image=img)
        assert view.ref == "frame0.jpg"

    def test_ref_none_for_anonymous_array(self) -> None:
        assert ViewInput(image=rgb()).ref is None

    def test_wrong_image_dtype_raises(self) -> None:
        with pytest.raises(ContractViolation, match="uint8"):
            ViewInput(image=np.zeros((4, 6, 3), dtype=np.float32))

    def test_wrong_channel_count_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"\(H, W, 3\)"):
            ViewInput(image=np.zeros((4, 6, 4), dtype=np.uint8))

    def test_empty_image_raises(self) -> None:
        with pytest.raises(ContractViolation, match=">= 1"):
            ViewInput(image=np.zeros((0, 6, 3), dtype=np.uint8))

    def test_wrong_image_type_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"ViewInput\.image"):
            ViewInput(image="frame0.jpg")  # type: ignore[arg-type]

    def test_empty_name_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"ViewInput\.name"):
            ViewInput(image=rgb(), name="")

    def test_wrong_component_types_raise(self) -> None:
        with pytest.raises(ContractViolation, match=r"ViewInput\.calibration"):
            ViewInput(image=rgb(), calibration="pinhole")  # type: ignore[arg-type]
        with pytest.raises(ContractViolation, match=r"ViewInput\.pose_prior"):
            ViewInput(image=rgb(), pose_prior=SE3.identity())  # type: ignore[arg-type]
        with pytest.raises(ContractViolation, match=r"ViewInput\.depth_prior"):
            ViewInput(image=rgb(), depth_prior=np.ones((4, 6), dtype=np.float32))  # type: ignore[arg-type]
        with pytest.raises(ContractViolation, match=r"ViewInput\.mask"):
            ViewInput(image=rgb(), mask=np.ones((4, 6), dtype=bool))  # type: ignore[arg-type]

    def test_matching_resolutions_accepted(self) -> None:
        ViewInput(
            image=rgb(4, 6),
            calibration=intrinsics(6, 4),
            depth_prior=DepthMap(depth=np.ones((4, 6), dtype=np.float32)),
            mask=Mask(mask=np.ones((4, 6), dtype=bool)),
            pose_prior=PosePrior(pose=SE3.identity()),
        )

    def test_mask_resolution_mismatch_raises(self) -> None:
        with pytest.raises(ContractViolation, match="resolution mismatch"):
            ViewInput(image=rgb(4, 6), mask=Mask(mask=np.ones((5, 6), dtype=bool)))

    def test_depth_resolution_mismatch_raises(self) -> None:
        with pytest.raises(ContractViolation, match="resolution mismatch"):
            ViewInput(
                image=rgb(4, 6),
                depth_prior=DepthMap(depth=np.ones((4, 7), dtype=np.float32)),
            )

    def test_calibration_resolution_mismatch_raises(self) -> None:
        with pytest.raises(ContractViolation, match="resolution mismatch"):
            ViewInput(image=rgb(4, 6), calibration=intrinsics(6, 5))

    def test_raymap_calibration_resolution_checked(self) -> None:
        directions = np.zeros((4, 6, 3), dtype=np.float32)
        directions[..., 2] = 1.0
        ViewInput(image=rgb(4, 6), calibration=Calibration.from_rays(RayMap(directions)))
        with pytest.raises(ContractViolation, match="resolution mismatch"):
            ViewInput(image=rgb(5, 6), calibration=Calibration.from_rays(RayMap(directions)))

    def test_path_image_with_consistent_components(self) -> None:
        # No in-memory image: components must still agree among themselves.
        img = MaterializedImage(name="f.jpg", abs_path=Path("f.jpg"))
        ViewInput(
            image=img,
            calibration=intrinsics(6, 4),
            depth_prior=DepthMap(depth=np.ones((4, 6), dtype=np.float32)),
        )
        with pytest.raises(ContractViolation, match="resolution mismatch"):
            ViewInput(
                image=img,
                calibration=intrinsics(6, 4),
                depth_prior=DepthMap(depth=np.ones((4, 7), dtype=np.float32)),
            )


class TestPosedViewSet:
    def _views(self, n: int = 2) -> tuple[ViewInput, ...]:
        return tuple(ViewInput(image=rgb(), name=f"v{i}") for i in range(n))

    def test_valid(self) -> None:
        views = self._views(2)
        poses = (SE3.identity(), SE3.identity())
        vs = PosedViewSet(views=views, poses=poses, frame=FrameMeta())
        assert len(vs) == 2

    def test_lists_normalized_to_tuples(self) -> None:
        vs = PosedViewSet(views=list(self._views(1)), poses=[SE3.identity()], frame=FrameMeta())
        assert isinstance(vs.views, tuple)
        assert isinstance(vs.poses, tuple)

    def test_empty_views_raises(self) -> None:
        with pytest.raises(ContractViolation, match="at least one view"):
            PosedViewSet(views=(), poses=(), frame=FrameMeta())

    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ContractViolation, match="one pose per view"):
            PosedViewSet(views=self._views(2), poses=(SE3.identity(),), frame=FrameMeta())

    def test_mixed_conventions_raise(self) -> None:
        poses = (SE3.identity(), SE3.identity(convention="opencv_world2cam"))
        with pytest.raises(ContractViolation, match="mixed pose conventions"):
            PosedViewSet(views=self._views(2), poses=poses, frame=FrameMeta())

    def test_wrong_view_type_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"PosedViewSet\.views\[0\]"):
            PosedViewSet(views=(rgb(),), poses=(SE3.identity(),), frame=FrameMeta())  # type: ignore[arg-type]

    def test_wrong_pose_type_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"PosedViewSet\.poses\[0\]"):
            PosedViewSet(views=self._views(1), poses=(np.eye(4),), frame=FrameMeta())  # type: ignore[arg-type]

    def test_wrong_frame_type_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"PosedViewSet\.frame"):
            PosedViewSet(views=self._views(1), poses=(SE3.identity(),), frame="world")  # type: ignore[arg-type]

    def test_non_sequence_views_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"PosedViewSet\.views"):
            PosedViewSet(views=42, poses=(SE3.identity(),), frame=FrameMeta())  # type: ignore[arg-type]
