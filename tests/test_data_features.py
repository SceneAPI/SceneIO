"""Validation tests for sceneapi_io.data.features."""

from __future__ import annotations

import numpy as np
import pytest

from sceneapi_io.data import (
    CorrespondenceGraph,
    FeatureSet,
    PairCorrespondences,
    TwoViewGeometry,
)
from sceneapi_io.errors import ContractViolation


def feature_set(n: int = 5, d: int = 8, dtype: type = np.float32) -> FeatureSet:
    rng = np.random.default_rng(n)
    return FeatureSet(
        keypoints=rng.uniform(0, 100, size=(n, 2)).astype(np.float32),
        descriptors=rng.uniform(0, 1, size=(n, d)).astype(dtype),
        scores=rng.uniform(0, 1, size=(n,)).astype(np.float32),
    )


class TestFeatureSet:
    def test_valid_full(self) -> None:
        fs = feature_set(5, 8)
        assert len(fs) == 5
        assert fs.descriptor_dtype == "float32"
        assert fs.descriptor_dim == 8

    def test_valid_keypoints_only(self) -> None:
        fs = FeatureSet(keypoints=np.zeros((3, 2), dtype=np.float32))
        assert fs.descriptor_dtype is None
        assert fs.descriptor_dim is None
        assert fs.scores is None

    def test_uint8_descriptor_dtype_tag(self) -> None:
        fs = feature_set(4, 32, dtype=np.uint8)
        assert fs.descriptor_dtype == "uint8"

    def test_empty_feature_set_allowed(self) -> None:
        fs = FeatureSet(keypoints=np.zeros((0, 2), dtype=np.float32))
        assert len(fs) == 0

    def test_keypoints_wrong_dtype_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"FeatureSet\.keypoints.*float32"):
            FeatureSet(keypoints=np.zeros((3, 2), dtype=np.float64))

    def test_keypoints_wrong_shape_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"FeatureSet\.keypoints"):
            FeatureSet(keypoints=np.zeros((3, 3), dtype=np.float32))

    def test_keypoints_non_finite_raises(self) -> None:
        kp = np.zeros((3, 2), dtype=np.float32)
        kp[0, 0] = np.inf
        with pytest.raises(ContractViolation, match="non-finite"):
            FeatureSet(keypoints=kp)

    def test_descriptor_row_mismatch_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"FeatureSet\.descriptors"):
            FeatureSet(
                keypoints=np.zeros((3, 2), dtype=np.float32),
                descriptors=np.zeros((4, 8), dtype=np.float32),
            )

    def test_non_numeric_descriptors_raise(self) -> None:
        with pytest.raises(ContractViolation, match="numeric dtype"):
            FeatureSet(
                keypoints=np.zeros((2, 2), dtype=np.float32),
                descriptors=np.zeros((2, 4), dtype=bool),
            )

    def test_scores_shape_mismatch_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"FeatureSet\.scores"):
            FeatureSet(
                keypoints=np.zeros((3, 2), dtype=np.float32),
                scores=np.zeros((4,), dtype=np.float32),
            )

    def test_scores_wrong_dtype_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"FeatureSet\.scores.*float32"):
            FeatureSet(
                keypoints=np.zeros((3, 2), dtype=np.float32),
                scores=np.zeros((3,), dtype=np.float64),
            )


class TestTwoViewGeometry:
    def test_valid(self) -> None:
        TwoViewGeometry(E=np.eye(3), num_inliers=12)

    def test_empty_allowed(self) -> None:
        TwoViewGeometry()

    @pytest.mark.parametrize("field_name", ["E", "F", "H"])
    def test_bad_matrix_shape_raises(self, field_name: str) -> None:
        with pytest.raises(ContractViolation, match=rf"TwoViewGeometry\.{field_name}"):
            TwoViewGeometry(**{field_name: np.eye(4)})

    def test_bad_matrix_dtype_raises(self) -> None:
        with pytest.raises(ContractViolation, match="float64"):
            TwoViewGeometry(F=np.eye(3, dtype=np.float32))

    @pytest.mark.parametrize("bad", [-1, 1.5, True])
    def test_bad_num_inliers_raises(self, bad: object) -> None:
        with pytest.raises(ContractViolation, match="num_inliers"):
            TwoViewGeometry(num_inliers=bad)  # type: ignore[arg-type]


class TestPairCorrespondences:
    def test_indexed_valid(self) -> None:
        pair = PairCorrespondences.from_indices(np.array([[0, 1], [2, 3]], dtype=np.int64))
        assert pair.mode == "indexed"
        assert len(pair) == 2

    def test_coordinates_valid(self) -> None:
        a = np.zeros((3, 2), dtype=np.float32)
        b = np.ones((3, 2), dtype=np.float32)
        pair = PairCorrespondences.from_coordinates(a, b)
        assert pair.mode == "coordinates"
        assert len(pair) == 3

    def test_unknown_mode_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"PairCorrespondences\.mode"):
            PairCorrespondences(mode="dense")  # type: ignore[arg-type]

    def test_indexed_missing_indices_raises(self) -> None:
        with pytest.raises(ContractViolation, match="requires indices"):
            PairCorrespondences(mode="indexed")

    def test_indexed_with_coordinates_raises(self) -> None:
        with pytest.raises(ContractViolation, match="must not carry"):
            PairCorrespondences(
                mode="indexed",
                indices=np.zeros((1, 2), dtype=np.int64),
                coordinates_a=np.zeros((1, 2), dtype=np.float32),
            )

    def test_coordinates_with_indices_raises(self) -> None:
        with pytest.raises(ContractViolation, match="must not carry"):
            PairCorrespondences(mode="coordinates", indices=np.zeros((1, 2), dtype=np.int64))

    def test_coordinates_missing_side_raises(self) -> None:
        with pytest.raises(ContractViolation, match="requires both"):
            PairCorrespondences(
                mode="coordinates", coordinates_a=np.zeros((1, 2), dtype=np.float32)
            )

    def test_indices_non_integer_raises(self) -> None:
        with pytest.raises(ContractViolation, match="integer dtype"):
            PairCorrespondences(mode="indexed", indices=np.zeros((2, 2), dtype=np.float32))

    def test_indices_negative_raises(self) -> None:
        with pytest.raises(ContractViolation, match="negative"):
            PairCorrespondences(mode="indexed", indices=np.array([[0, -1]], dtype=np.int64))

    def test_indices_wrong_shape_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"PairCorrespondences\.indices"):
            PairCorrespondences(mode="indexed", indices=np.zeros((2, 3), dtype=np.int64))

    def test_coordinate_length_mismatch_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"coordinates_b"):
            PairCorrespondences.from_coordinates(
                np.zeros((3, 2), dtype=np.float32), np.zeros((2, 2), dtype=np.float32)
            )

    def test_coordinates_wrong_dtype_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"coordinates_a.*float32"):
            PairCorrespondences.from_coordinates(
                np.zeros((3, 2), dtype=np.float64), np.zeros((3, 2), dtype=np.float32)
            )

    def test_scores_length_mismatch_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"PairCorrespondences\.scores"):
            PairCorrespondences.from_indices(
                np.zeros((2, 2), dtype=np.int64),
                scores=np.zeros((3,), dtype=np.float32),
            )

    def test_geometry_wrong_type_raises(self) -> None:
        with pytest.raises(ContractViolation, match=r"PairCorrespondences\.geometry"):
            PairCorrespondences.from_indices(
                np.zeros((1, 2), dtype=np.int64),
                geometry=np.eye(3),  # type: ignore[arg-type]
            )

    def test_geometry_attached(self) -> None:
        pair = PairCorrespondences.from_indices(
            np.zeros((1, 2), dtype=np.int64),
            geometry=TwoViewGeometry(E=np.eye(3), num_inliers=1),
        )
        assert pair.geometry is not None
        assert pair.geometry.num_inliers == 1


class TestCorrespondenceGraph:
    def _graph_inputs(self) -> tuple[dict, dict]:
        features = {"a.jpg": feature_set(5), "b.jpg": feature_set(4)}
        pairs = {
            ("a.jpg", "b.jpg"): PairCorrespondences.from_indices(
                np.array([[0, 0], [4, 3]], dtype=np.int64)
            )
        }
        return features, pairs

    def test_valid_indexed_graph(self) -> None:
        features, pairs = self._graph_inputs()
        graph = CorrespondenceGraph(features=features, pairs=pairs)
        assert set(graph.features) == {"a.jpg", "b.jpg"}
        assert len(graph.pairs[("a.jpg", "b.jpg")]) == 2

    def test_detector_free_graph_needs_no_features(self) -> None:
        pairs = {
            ("a.jpg", "b.jpg"): PairCorrespondences.from_coordinates(
                np.zeros((2, 2), dtype=np.float32), np.ones((2, 2), dtype=np.float32)
            )
        }
        graph = CorrespondenceGraph(features={}, pairs=pairs)
        assert graph.features == {}

    def test_empty_image_id_raises(self) -> None:
        with pytest.raises(ContractViolation, match="image ids must be non-empty"):
            CorrespondenceGraph(features={"": feature_set(2)}, pairs={})

    def test_non_featureset_value_raises(self) -> None:
        with pytest.raises(ContractViolation, match="expected FeatureSet"):
            CorrespondenceGraph(features={"a.jpg": np.zeros((2, 2))}, pairs={})  # type: ignore[dict-item]

    def test_bad_pair_key_raises(self) -> None:
        with pytest.raises(ContractViolation, match="keys must be"):
            CorrespondenceGraph(
                features={},
                pairs={
                    "a.jpg-b.jpg": PairCorrespondences.from_coordinates(  # type: ignore[dict-item]
                        np.zeros((1, 2), dtype=np.float32), np.zeros((1, 2), dtype=np.float32)
                    )
                },
            )

    def test_self_pair_raises(self) -> None:
        with pytest.raises(ContractViolation, match="self-pair"):
            CorrespondenceGraph(
                features={"a.jpg": feature_set(3)},
                pairs={
                    ("a.jpg", "a.jpg"): PairCorrespondences.from_indices(
                        np.zeros((1, 2), dtype=np.int64)
                    )
                },
            )

    def test_non_pair_value_raises(self) -> None:
        with pytest.raises(ContractViolation, match="expected PairCorrespondences"):
            CorrespondenceGraph(features={}, pairs={("a.jpg", "b.jpg"): "matches"})  # type: ignore[dict-item]

    def test_indexed_pair_missing_featureset_raises(self) -> None:
        pairs = {
            ("a.jpg", "b.jpg"): PairCorrespondences.from_indices(np.zeros((1, 2), dtype=np.int64))
        }
        with pytest.raises(ContractViolation, match="no FeatureSet"):
            CorrespondenceGraph(features={"a.jpg": feature_set(3)}, pairs=pairs)

    def test_indexed_pair_out_of_range_raises(self) -> None:
        features = {"a.jpg": feature_set(5), "b.jpg": feature_set(4)}
        pairs = {
            ("a.jpg", "b.jpg"): PairCorrespondences.from_indices(
                np.array([[0, 4]], dtype=np.int64)  # 4 out of range for b (len 4)
            )
        }
        with pytest.raises(ContractViolation, match="out of range"):
            CorrespondenceGraph(features=features, pairs=pairs)
