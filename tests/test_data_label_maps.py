"""Contract and independent arithmetic tests for dense label records."""

from __future__ import annotations

import numpy as np
import pytest

from sceneio.data import (
    InstanceMap,
    LabelTaxonomy,
    Mask,
    PanopticMap,
    SemanticMap,
)
from sceneio.errors import ContractViolation


def _taxonomy() -> LabelTaxonomy:
    return LabelTaxonomy(
        np.array([1, 4, 9], np.int32),
        ("floor", "cube", "sphere"),
        "org.kubric.movi-a",
        "61f2422c",
        display_colors=np.array(
            [[80, 80, 80], [255, 0, 0], [0, 0, 255]], np.uint8
        ),
        is_thing=np.array([False, True, True]),
    )


def _panoptic(*, valid: np.ndarray | None = None) -> PanopticMap:
    classes = np.array([[1, 4, 4], [-1, 9, 9]], np.int32)
    instances = np.array([[0, 7, 7], [0, 2**40, 2**40]], np.int64)
    semantic = SemanticMap(classes, -1, valid, _taxonomy())
    instance = InstanceMap(
        instances,
        0,
        valid,
        np.array([7, 2**40], np.int64),
        np.array([4, 9], np.int32),
    )
    return PanopticMap(semantic, instance)


def test_taxonomy_is_ordered_explicit_and_zero_copy() -> None:
    ids = np.array([9, 1, 4], np.int32)
    names = ["sphere", "floor", "cube"]
    taxonomy = LabelTaxonomy(ids, names, "org.kubric.movi-a", "61f2422c")
    assert taxonomy.semantic_ids is ids
    assert taxonomy.names == tuple(names)
    assert taxonomy.identity == "org.kubric.movi-a"
    assert taxonomy.version == "61f2422c"
    assert taxonomy.index(1) == 1
    with pytest.raises(KeyError, match="semantic id 8"):
        taxonomy.index(8)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("semantic_ids", np.array([1, 2], np.int64), "dtype int32"),
        ("semantic_ids", np.array([[1, 2]], np.int32), "1-D"),
        ("semantic_ids", np.array([1, 1], np.int32), "unique"),
        ("names", ("only-one",), "one name per semantic id"),
        ("identity", "", "non-empty string"),
        ("version", "bad\0version", "without NUL"),
        ("display_colors", np.zeros((2, 4), np.uint8), "shape"),
        ("is_thing", np.zeros(3, np.bool_), "shape"),
    ],
)
def test_taxonomy_refuses_inconsistent_fields(
    field: str, replacement: object, message: str
) -> None:
    values: dict[str, object] = {
        "semantic_ids": np.array([1, 2], np.int32),
        "names": ("one", "two"),
        "identity": "example",
        "version": "v1",
        "display_colors": np.zeros((2, 3), np.uint8),
        "is_thing": np.zeros(2, np.bool_),
    }
    values[field] = replacement
    with pytest.raises(ContractViolation, match=message):
        LabelTaxonomy(**values)  # type: ignore[arg-type]


def test_taxonomy_refuses_noncontiguous_arrays() -> None:
    with pytest.raises(ContractViolation, match="C-contiguous"):
        LabelTaxonomy(
            np.arange(8, dtype=np.int32)[::2],
            ("a", "b", "c", "d"),
            "example",
            "v1",
        )


@pytest.mark.parametrize("names", ["ab", None, 7])
def test_taxonomy_refuses_non_sequence_names(names: object) -> None:
    with pytest.raises(ContractViolation, match="tuple or list of strings"):
        LabelTaxonomy(
            np.array([1, 2], np.int32),
            names,  # type: ignore[arg-type]
            "example",
            "v1",
        )


def test_semantic_map_void_validity_and_taxonomy_contract() -> None:
    classes = np.array([[1, 4], [12345, -1]], np.int32)
    valid = np.array([[True, True], [False, True]])
    semantic = SemanticMap(classes, -1, valid, _taxonomy())
    assert semantic.class_ids is classes
    assert semantic.valid is valid
    assert semantic.shape == (2, 2)

    invalid_unknown = classes.copy()
    invalid_unknown[0, 0] = 12345
    with pytest.raises(ContractViolation, match="absent from the table"):
        SemanticMap(invalid_unknown, -1, valid, _taxonomy())


def test_semantic_map_refuses_wrong_layout_and_ambiguous_void() -> None:
    with pytest.raises(ContractViolation, match="dtype int32"):
        SemanticMap(np.zeros((2, 3), np.uint32), -1)
    with pytest.raises(ContractViolation, match="C-contiguous"):
        SemanticMap(np.zeros((3, 4), np.int32)[:, ::2], -1)
    with pytest.raises(ContractViolation, match="void must not"):
        SemanticMap(np.ones((1, 1), np.int32), 1, taxonomy=_taxonomy())
    with pytest.raises(ContractViolation, match="outside int32"):
        SemanticMap(np.zeros((1, 1), np.int32), 2**40)


def test_instance_map_supports_int64_ids_and_empty_instance_table() -> None:
    empty = InstanceMap(
        np.zeros((2, 3), np.int64),
        0,
        table_instance_ids=np.array([], np.int64),
        table_semantic_ids=np.array([], np.int32),
    )
    assert empty.shape == (2, 3)

    large = 2**48 + 17
    values = np.array([[0, large]], np.int64)
    mapped = InstanceMap(
        values,
        0,
        table_instance_ids=np.array([large], np.int64),
        table_semantic_ids=np.array([9], np.int32),
    )
    assert int(mapped.instance_ids[0, 1]) == large


def test_instance_map_table_is_all_or_nothing_and_covers_valid_foreground() -> None:
    values = np.array([[0, 7], [99, 7]], np.int64)
    valid = np.array([[True, True], [False, True]])
    InstanceMap(
        values,
        0,
        valid,
        np.array([7], np.int64),
        np.array([4], np.int32),
    )
    with pytest.raises(ContractViolation, match="present together"):
        InstanceMap(values, 0, table_instance_ids=np.array([7], np.int64))
    with pytest.raises(ContractViolation, match="ids must be unique"):
        InstanceMap(
            values,
            0,
            table_instance_ids=np.array([7, 7], np.int64),
            table_semantic_ids=np.array([4, 4], np.int32),
        )
    with pytest.raises(ContractViolation, match="background_id"):
        InstanceMap(
            values,
            0,
            table_instance_ids=np.array([0, 7, 99], np.int64),
            table_semantic_ids=np.array([1, 4, 9], np.int32),
        )
    with pytest.raises(ContractViolation, match="absent from the table"):
        InstanceMap(
            values,
            0,
            table_instance_ids=np.array([7], np.int64),
            table_semantic_ids=np.array([4], np.int32),
        )


def test_instance_membership_small_lookup_and_large_span_paths_are_exact() -> None:
    minimum = np.iinfo(np.int64).min
    with pytest.raises(ContractViolation, match="absent from the table"):
        InstanceMap(
            np.array([[minimum + 1]], np.int64),
            0,
            table_instance_ids=np.array([minimum, minimum + 2], np.int64),
            table_semantic_ids=np.array([1, 2], np.int32),
        )
    maximum = np.iinfo(np.int64).max
    mapped = InstanceMap(
        np.array([[minimum, maximum]], np.int64),
        0,
        table_instance_ids=np.array([minimum, maximum], np.int64),
        table_semantic_ids=np.array([1, 2], np.int32),
    )
    assert mapped.shape == (1, 2)


def test_panoptic_map_composes_children_without_copying() -> None:
    semantic = SemanticMap(np.array([[1]], np.int32), -1)
    instance = InstanceMap(np.array([[0]], np.int64), 0)
    panoptic = PanopticMap(semantic, instance)
    assert panoptic.shape == (1, 1)
    assert panoptic.semantic is semantic
    assert panoptic.instance is instance
    assert panoptic.valid is None


def test_panoptic_map_requires_matching_shape_and_validity() -> None:
    semantic = SemanticMap(np.zeros((2, 2), np.int32), -1)
    with pytest.raises(ContractViolation, match="shapes must be identical"):
        PanopticMap(semantic, InstanceMap(np.zeros((3, 2), np.int64), 0))

    left = np.array([[True, False]])
    right = np.array([[True, True]])
    with pytest.raises(ContractViolation, match="validity must be identical"):
        PanopticMap(
            SemanticMap(np.array([[1, -1]], np.int32), -1, left),
            InstanceMap(np.array([[0, 0]], np.int64), 0, right),
        )


def test_panoptic_map_refuses_void_foreground_and_table_disagreement() -> None:
    with pytest.raises(ContractViolation, match="void pixels"):
        PanopticMap(
            SemanticMap(np.array([[-1]], np.int32), -1),
            InstanceMap(np.array([[7]], np.int64), 0),
        )
    with pytest.raises(ContractViolation, match="table disagrees"):
        PanopticMap(
            SemanticMap(np.array([[4]], np.int32), -1, taxonomy=_taxonomy()),
            InstanceMap(
                np.array([[7]], np.int64),
                0,
                table_instance_ids=np.array([7], np.int64),
                table_semantic_ids=np.array([9], np.int32),
            ),
        )


def test_packed_conversion_matches_independent_numpy_formula() -> None:
    semantic = np.array([[0, 3, 3], [8, 8, 0]], np.int32)
    instance = np.array([[0, 17, 18], [4, 5, 0]], np.int64)
    expected = semantic.astype(np.uint32) * np.uint32(1000) + instance.astype(
        np.uint32
    )
    decoded = PanopticMap.from_packed(
        expected,
        divisor=1000,
        void_id=0,
        background_id=0,
    )
    np.testing.assert_array_equal(decoded.semantic.class_ids, semantic)
    np.testing.assert_array_equal(decoded.instance.instance_ids, instance)
    np.testing.assert_array_equal(decoded.to_packed(divisor=1000, dtype=np.uint32), expected)


@pytest.mark.parametrize("dtype", [np.int8, np.uint8, np.int16, np.uint16])
def test_packed_decode_promotes_small_integer_arithmetic(dtype: object) -> None:
    packed = np.array([[100]], dtype=dtype)
    decoded = PanopticMap.from_packed(
        packed,
        divisor=1000,
        void_id=-1,
        background_id=0,
    )
    np.testing.assert_array_equal(decoded.semantic.class_ids, [[0]])
    np.testing.assert_array_equal(decoded.instance.instance_ids, [[100]])
    assert decoded.semantic.void_id == -1


def test_packed_decode_preserves_uint64_domain() -> None:
    divisor = np.iinfo(np.int64).max
    packed = np.array([[np.iinfo(np.uint64).max]], np.uint64)
    decoded = PanopticMap.from_packed(
        packed,
        divisor=divisor,
        void_id=-1,
        background_id=0,
    )
    np.testing.assert_array_equal(decoded.semantic.class_ids, [[2]])
    np.testing.assert_array_equal(decoded.instance.instance_ids, [[1]])


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (lambda p: p.to_packed(divisor=0), "positive"),
        (
            lambda _p: PanopticMap(
                SemanticMap(np.array([[1]], np.int32), 0),
                InstanceMap(np.array([[7]], np.int64), 0),
            ).to_packed(divisor=5),
            "id < divisor",
        ),
        (
            lambda _p: PanopticMap.from_packed(
                np.array([[1999]], np.int64),
                divisor=1000,
                void_id=0,
                background_id=0,
            ).to_packed(divisor=1000, dtype=np.uint8),
            "exceed uint8",
        ),
        (
            lambda _p: PanopticMap.from_packed(
                np.array([[-1]], np.int64),
                divisor=1000,
                void_id=0,
                background_id=0,
            ),
            "nonnegative",
        ),
        (lambda p: p.to_packed(divisor=1000, dtype="wat"), "plain integer"),
        (lambda p: p.to_packed(divisor=1000, dtype=object()), "plain integer"),
    ],
)
def test_packed_conversion_refuses_loss(
    operation, message: str
) -> None:
    with pytest.raises(ContractViolation, match=message):
        operation(_panoptic())


def test_existing_mask_contract_remains_boolean_only() -> None:
    mask = Mask(np.array([[True, False]], np.bool_))
    assert mask.shape == (1, 2)
    with pytest.raises(ContractViolation, match="dtype bool"):
        Mask(np.array([[1, 0]], np.int32))
