"""Validation tests for sceneio.data.pointcloud and .priors."""

from __future__ import annotations

import numpy as np
import pytest

from sceneio.data import SE3, PosePrior, TrackedPointCloud, TrackObservation
from sceneio.errors import ContractViolation


class TestTrackObservation:
    def test_valid(self) -> None:
        obs = TrackObservation(image_id="a.jpg", keypoint_idx=3)
        assert obs.keypoint_idx == 3

    @pytest.mark.parametrize("bad", ["", 3, None])
    def test_bad_image_id_raises(self, bad: object) -> None:
        with pytest.raises(ContractViolation, match="image_id"):
            TrackObservation(image_id=bad, keypoint_idx=0)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", [-1, 1.5, "0", True])
    def test_bad_keypoint_idx_raises(self, bad: object) -> None:
        with pytest.raises(ContractViolation, match="keypoint_idx"):
            TrackObservation(image_id="a.jpg", keypoint_idx=bad)  # type: ignore[arg-type]


class TestTrackedPointCloud:
    def test_valid_full(self) -> None:
        cloud = TrackedPointCloud(
            xyz=np.zeros((2, 3), dtype=np.float32),
            rgb=np.zeros((2, 3), dtype=np.uint8),
            tracks=(
                (TrackObservation("a.jpg", 0), TrackObservation("b.jpg", 1)),
                (),
            ),
        )
        assert len(cloud) == 2
        assert cloud.tracks is not None
        assert len(cloud.tracks[0]) == 2

    def test_float64_xyz_accepted(self) -> None:
        TrackedPointCloud(xyz=np.zeros((3, 3), dtype=np.float64))

    def test_tracks_lists_normalized_to_tuples(self) -> None:
        cloud = TrackedPointCloud(
            xyz=np.zeros((1, 3), dtype=np.float32),
            tracks=[[TrackObservation("a.jpg", 0)]],
        )
        assert isinstance(cloud.tracks, tuple)
        assert isinstance(cloud.tracks[0], tuple)

    def test_xyz_wrong_shape_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"TrackedPointCloud\.xyz"):
            TrackedPointCloud(xyz=np.zeros((2, 2), dtype=np.float32))

    def test_xyz_wrong_dtype_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"TrackedPointCloud\.xyz"):
            TrackedPointCloud(xyz=np.zeros((2, 3), dtype=np.int32))

    def test_xyz_non_finite_raises(self) -> None:
        xyz = np.zeros((2, 3), dtype=np.float32)
        xyz[0, 0] = np.nan
        with pytest.raises(ContractViolation, match="non-finite"):
            TrackedPointCloud(xyz=xyz)

    def test_rgb_wrong_dtype_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"TrackedPointCloud\.rgb.*uint8"):
            TrackedPointCloud(
                xyz=np.zeros((2, 3), dtype=np.float32),
                rgb=np.zeros((2, 3), dtype=np.float32),
            )

    def test_rgb_length_mismatch_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"TrackedPointCloud\.rgb"):
            TrackedPointCloud(
                xyz=np.zeros((2, 3), dtype=np.float32),
                rgb=np.zeros((3, 3), dtype=np.uint8),
            )

    def test_tracks_length_mismatch_raises(self) -> None:
        with pytest.raises(ContractViolation, match="one track per point"):
            TrackedPointCloud(xyz=np.zeros((2, 3), dtype=np.float32), tracks=((),))

    def test_tracks_not_a_sequence_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"TrackedPointCloud\.tracks"):
            TrackedPointCloud(xyz=np.zeros((1, 3), dtype=np.float32), tracks=42)  # type: ignore[arg-type]

    def test_track_entry_not_a_sequence_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"tracks\[0\]"):
            TrackedPointCloud(xyz=np.zeros((1, 3), dtype=np.float32), tracks=(42,))  # type: ignore[arg-type]

    def test_track_obs_wrong_type_raises(self) -> None:
        with pytest.raises(ContractViolation, match="TrackObservation entries"):
            TrackedPointCloud(
                xyz=np.zeros((1, 3), dtype=np.float32),
                tracks=((("a.jpg", 0),),),  # type: ignore[arg-type]
            )


class TestPosePrior:
    def test_valid_minimal(self) -> None:
        prior = PosePrior(pose=SE3.identity())
        assert prior.weight is None
        assert prior.covariance is None
        assert prior.is_metric is False

    def test_valid_full(self) -> None:
        prior = PosePrior(
            pose=SE3.identity(),
            weight=2,
            covariance=np.eye(6),
            is_metric=True,
        )
        assert prior.weight == 2.0
        assert isinstance(prior.weight, float)
        assert prior.covariance is not None
        assert prior.covariance.dtype == np.float64

    def test_non_se3_pose_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"PosePrior\.pose"):
            PosePrior(pose=np.eye(4))  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf")])
    def test_bad_weight_raises(self, bad: float) -> None:
        with pytest.raises(ContractViolation, match=r"PosePrior\.weight"):
            PosePrior(pose=SE3.identity(), weight=bad)

    def test_non_numeric_weight_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"PosePrior\.weight"):
            PosePrior(pose=SE3.identity(), weight="1.0")  # type: ignore[arg-type]

    def test_bool_weight_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"PosePrior\.weight"):
            PosePrior(pose=SE3.identity(), weight=True)

    def test_covariance_wrong_shape_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"PosePrior\.covariance"):
            PosePrior(pose=SE3.identity(), covariance=np.eye(3))

    def test_covariance_non_finite_raises(self) -> None:
        cov = np.eye(6)
        cov[0, 0] = np.inf
        with pytest.raises(ContractViolation, match="non-finite"):
            PosePrior(pose=SE3.identity(), covariance=cov)

    def test_non_bool_is_metric_raises(self) -> None:
        with pytest.raises(ContractViolation, match="is_metric"):
            PosePrior(pose=SE3.identity(), is_metric=1)  # type: ignore[arg-type]
