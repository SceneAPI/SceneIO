"""Validation tests for sceneapi_io.mapping contract types."""

from __future__ import annotations

import numpy as np
import pytest

from sceneapi_io.data import (
    SE3,
    Calibration,
    CameraIntrinsics,
    CameraModel,
    ConfidenceMap,
    FrameMeta,
    Pointmap,
    TrackedPointCloud,
)
from sceneapi_io.errors import ContractViolation
from sceneapi_io.mapping import MapperTraits, MappingOptions, MappingResult

TRAITS_KW = {
    "requires_correspondences": False,
    "accepts_pose_priors": True,
    "accepts_depth_priors": True,
    "accepts_calibration": True,
    "emits_dense": True,
    "metric_capable": False,
}


def dense_pair(h: int = 4, w: int = 4) -> tuple[Pointmap, ConfidenceMap]:
    return (
        Pointmap(points=np.zeros((h, w, 3), dtype=np.float32)),
        ConfidenceMap(values=np.full((h, w), 0.5, dtype=np.float32)),
    )


class TestMapperTraits:
    def test_valid(self) -> None:
        traits = MapperTraits(**TRAITS_KW)
        assert traits.requires_correspondences is False
        assert traits.emits_dense is True

    @pytest.mark.parametrize("field_name", sorted(TRAITS_KW))
    def test_non_bool_field_raises(self, field_name: str) -> None:
        kwargs = {**TRAITS_KW, field_name: 1}
        with pytest.raises(ContractViolation, match=rf"MapperTraits\.{field_name}"):
            MapperTraits(**kwargs)  # type: ignore[arg-type]


class TestMappingOptions:
    def test_defaults(self) -> None:
        options = MappingOptions()
        assert options.max_views is None
        assert options.seed is None
        assert options.extra == {}

    def test_extra_is_copied_to_dict(self) -> None:
        source = {"colmap.mapper.ba_refine_focal_length": True}
        options = MappingOptions(extra=source)
        source["colmap.mapper.ba_refine_focal_length"] = False
        assert options.extra == {"colmap.mapper.ba_refine_focal_length": True}

    @pytest.mark.parametrize("bad", [0, -3, 1.5, True, "10"])
    def test_bad_max_views_raises(self, bad: object) -> None:
        with pytest.raises(ContractViolation, match="max_views"):
            MappingOptions(max_views=bad)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", [1.5, True, "7"])
    def test_bad_seed_raises(self, bad: object) -> None:
        with pytest.raises(ContractViolation, match="seed"):
            MappingOptions(seed=bad)  # type: ignore[arg-type]

    def test_non_mapping_extra_raises(self) -> None:
        with pytest.raises(ContractViolation, match="extra"):
            MappingOptions(extra=[("k", "v")])  # type: ignore[arg-type]


class TestMappingResult:
    def _poses(self, n: int = 2) -> tuple[SE3, ...]:
        return tuple(SE3.identity() for _ in range(n))

    def test_minimal_valid(self) -> None:
        result = MappingResult(poses=self._poses(2), frame=FrameMeta())
        assert len(result) == 2
        assert result.calibrations is None
        assert result.dense is None
        assert result.stats == {}

    def test_full_valid(self) -> None:
        calibration = Calibration.from_intrinsics(
            CameraIntrinsics(
                model=CameraModel.SIMPLE_PINHOLE,
                width=4,
                height=4,
                params=np.array([4.0, 2.0, 2.0]),
            )
        )
        result = MappingResult(
            poses=self._poses(2),
            frame=FrameMeta(scale="metric", scale_provenance="prior_anchored"),
            calibrations=(calibration, calibration),
            geometry=TrackedPointCloud(xyz=np.zeros((3, 3), dtype=np.float32)),
            dense=(dense_pair(), dense_pair()),
            stats={"num_registered": 2},
        )
        assert result.dense is not None
        assert result.stats["num_registered"] == 2

    def test_sequences_normalized_to_tuples(self) -> None:
        result = MappingResult(poses=[SE3.identity()], frame=FrameMeta(), dense=[dense_pair()])
        assert isinstance(result.poses, tuple)
        assert isinstance(result.dense, tuple)

    def test_empty_poses_raises(self) -> None:
        with pytest.raises(ContractViolation, match="at least one pose"):
            MappingResult(poses=(), frame=FrameMeta())

    def test_wrong_pose_type_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"MappingResult\.poses\[0\]"):
            MappingResult(poses=(np.eye(4),), frame=FrameMeta())  # type: ignore[arg-type]

    def test_mixed_conventions_raise(self) -> None:
        poses = (SE3.identity(), SE3.identity(convention="opencv_world2cam"))
        with pytest.raises(ContractViolation, match="mixed pose conventions"):
            MappingResult(poses=poses, frame=FrameMeta())

    def test_wrong_frame_type_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"MappingResult\.frame"):
            MappingResult(poses=self._poses(1), frame="world")  # type: ignore[arg-type]

    def test_calibrations_length_mismatch_raises(self) -> None:
        calibration = Calibration.from_intrinsics(
            CameraIntrinsics(
                model=CameraModel.SIMPLE_PINHOLE,
                width=4,
                height=4,
                params=np.array([4.0, 2.0, 2.0]),
            )
        )
        with pytest.raises(ContractViolation, match="one per view"):
            MappingResult(poses=self._poses(2), frame=FrameMeta(), calibrations=(calibration,))

    def test_wrong_geometry_type_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"MappingResult\.geometry"):
            MappingResult(
                poses=self._poses(1),
                frame=FrameMeta(),
                geometry=np.zeros((3, 3)),  # type: ignore[arg-type]
            )

    def test_dense_length_mismatch_raises(self) -> None:
        with pytest.raises(ContractViolation, match="per view"):
            MappingResult(poses=self._poses(2), frame=FrameMeta(), dense=(dense_pair(),))

    def test_dense_non_pair_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"dense\[0\]"):
            MappingResult(
                poses=self._poses(1),
                frame=FrameMeta(),
                dense=(dense_pair()[0],),  # type: ignore[arg-type]
            )

    def test_dense_wrong_member_types_raise(self) -> None:
        pointmap, confidence = dense_pair()
        with pytest.raises(ContractViolation, match=r"dense\[0\]\[0\]"):
            MappingResult(
                poses=self._poses(1),
                frame=FrameMeta(),
                dense=((confidence, confidence),),  # type: ignore[arg-type]
            )
        with pytest.raises(ContractViolation, match=r"dense\[0\]\[1\]"):
            MappingResult(
                poses=self._poses(1),
                frame=FrameMeta(),
                dense=((pointmap, pointmap),),  # type: ignore[arg-type]
            )

    def test_dense_resolution_mismatch_raises(self) -> None:
        pointmap, _ = dense_pair(4, 4)
        _, confidence = dense_pair(4, 5)
        with pytest.raises(ContractViolation, match="shape"):
            MappingResult(poses=self._poses(1), frame=FrameMeta(), dense=((pointmap, confidence),))

    def test_non_mapping_stats_raises(self) -> None:
        with pytest.raises(ContractViolation, match="stats"):
            MappingResult(poses=self._poses(1), frame=FrameMeta(), stats=[1, 2])  # type: ignore[arg-type]
