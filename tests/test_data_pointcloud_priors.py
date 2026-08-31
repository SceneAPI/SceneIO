"""Validation tests for sceneio.pointcloud and .priors."""

from __future__ import annotations

import numpy as np
import pytest

import sceneio
from sceneio import SE3, PosePrior, TrackObservation, point_cloud
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


class TestPointCloudTracks:
    def test_valid_full(self) -> None:
        cloud = point_cloud(
            np.zeros((2, 3), dtype=np.float32),
            colors=np.zeros((2, 3), dtype=np.uint8),
            tracks=(
                (TrackObservation("a.jpg", 0), TrackObservation("b.jpg", 1)),
                (),
            ),
        )
        assert cloud.num_points == 2
        assert cloud.has_tracks and cloud.tracks is not None
        assert len(cloud.tracks[0]) == 2
        np.testing.assert_array_equal(cloud.track_offsets, [0, 2, 2])
        assert tuple(cloud.track_image_ids) == ("a.jpg", "b.jpg")
        np.testing.assert_array_equal(cloud.track_keypoint_indices, [0, 1])

    def test_untracked_cloud_uses_same_type(self) -> None:
        cloud = point_cloud(np.zeros((3, 3), dtype=np.float32))
        assert not cloud.has_tracks
        assert cloud.tracks is None

    def test_tracks_lists_normalized_to_tuples(self) -> None:
        cloud = point_cloud(
            np.zeros((1, 3), dtype=np.float32),
            tracks=[[TrackObservation("a.jpg", 0)]],
        )
        assert isinstance(cloud.tracks, tuple)
        assert isinstance(cloud.tracks[0], tuple)

    def test_xyz_wrong_shape_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"PointCloud\.positions"):
            point_cloud(np.zeros((2, 2), dtype=np.float32))

    def test_xyz_wrong_dtype_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"PointCloud\.positions"):
            point_cloud(np.zeros((2, 3), dtype=np.int32))

    def test_source_float_payload_semantics_remain_available(self) -> None:
        xyz = np.zeros((2, 3), dtype=np.float32)
        xyz[0, 0] = np.nan
        cloud = point_cloud(xyz)
        assert np.isnan(cloud.positions[0, 0])

    def test_rgb_wrong_dtype_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"PointCloud\.colors.*uint8"):
            point_cloud(
                np.zeros((2, 3), dtype=np.float32),
                colors=np.zeros((2, 3), dtype=np.float32),
            )

    def test_rgb_length_mismatch_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"PointCloud"):
            point_cloud(
                np.zeros((2, 3), dtype=np.float32),
                colors=np.zeros((3, 3), dtype=np.uint8),
            )

    def test_tracks_length_mismatch_raises(self) -> None:
        with pytest.raises(ContractViolation, match="one track per point"):
            point_cloud(np.zeros((2, 3), dtype=np.float32), tracks=((),))

    def test_tracks_not_a_sequence_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"PointCloud\.tracks"):
            point_cloud(np.zeros((1, 3), dtype=np.float32), tracks=42)  # type: ignore[arg-type]

    def test_track_entry_not_a_sequence_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"tracks\[0\]"):
            point_cloud(np.zeros((1, 3), dtype=np.float32), tracks=(42,))  # type: ignore[arg-type]

    def test_track_obs_wrong_type_raises(self) -> None:
        with pytest.raises(ContractViolation, match="TrackObservation entries"):
            point_cloud(
                np.zeros((1, 3), dtype=np.float32),
                tracks=((("a.jpg", 0),),),  # type: ignore[arg-type]
            )

    def test_canonical_csr_input(self) -> None:
        cloud = point_cloud(
            np.zeros((2, 3), dtype=np.float32),
            track_offsets=np.array([0, 1, 1], dtype=np.uint64),
            track_image_ids=("a.jpg",),
            track_keypoint_indices=np.array([7], dtype=np.uint64),
        )
        assert cloud.tracks == ((TrackObservation("a.jpg", 7),), ())

    def test_point_codec_refuses_tracks_without_touching_destination(self, tmp_path) -> None:
        cloud = point_cloud(
            np.zeros((1, 3), dtype=np.float32),
            tracks=((TrackObservation("a.jpg", 0),),),
        )
        destination = tmp_path / "tracked.xyz"
        with pytest.raises(sceneio.FormatError, match="tracks"):
            sceneio.write(cloud, destination, format="xyz")
        assert not destination.exists()


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
