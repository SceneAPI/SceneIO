"""Focused FC2 label projections for NCore V4 camera-label components."""

from __future__ import annotations

import gc
from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import InstanceMap, LabelTaxonomy, PanopticMap, SemanticMap
from sceneio.io._ncore.model import (
    NCoreArray,
    NCoreComponent,
    NCoreComponentData,
    NCoreGroup,
    NCoreItem,
    NCoreSelection,
)
from sceneio.io._ncore.profiles.scene import (
    _label_descriptor,
    read_camera_labels_profile,
)
from sceneio.io._ncore.projection import _component_data_from_sceneio_label_map


def _item(
    qualifier: str,
    data: np.ndarray,
    metadata: dict[str, object],
    *,
    dtype: str | None = None,
) -> NCoreItem:
    schema_dtype = dtype or data.dtype.str
    descriptor = {
        "camera_id": "front",
        "label_type": {
            "category": "SEGMENTATION",
            "qualifier": qualifier,
            "unit": "UNITLESS",
        },
        "label_schema": {
            "dtype": schema_dtype,
            "shape_suffix": [],
            "encoding": "RAW",
            "encoded_format": None,
            "quantization": None,
        },
        "label_source": "GT_SYNTHETIC",
        "generic_meta_data": {
            "__sceneio_label_map_v1__": {
                "schema": "sceneio.label_map/1",
                "kind": qualifier,
                **metadata,
            }
        },
    }
    return NCoreItem(
        "camera_label",
        f"{qualifier}@front",
        {"data": data},
        {"descriptor": descriptor},
        timestamp_us=123,
        reference_frame_id="front",
    )


def _taxonomy() -> LabelTaxonomy:
    return LabelTaxonomy(
        np.array([0, 4, 9], dtype=np.int32),
        ("background", "vehicle", "pedestrian"),
        "example.taxonomy",
        "v2",
        np.array([[0, 0, 0], [255, 1, 2], [3, 4, 255]], dtype=np.uint8),
        np.array([False, True, True], dtype=bool),
    )


def test_ncore_segmentation_projection_matches_independent_arrays() -> None:
    taxonomy = _taxonomy()
    semantic = sceneio.project_ncore_item(
        _item(
            "semantic",
            np.array([[0, 4], [9, -1]], dtype=np.int32),
            {
                "semantic_void_id": -1,
                "taxonomy_semantic_ids": [0, 4, 9],
                "taxonomy_names": ["background", "vehicle", "pedestrian"],
                "taxonomy_identity": taxonomy.identity,
                "taxonomy_version": taxonomy.version,
                "taxonomy_display_colors": taxonomy.display_colors.tolist(),
                "taxonomy_is_thing": taxonomy.is_thing.tolist(),
            },
        )
    )
    assert isinstance(semantic, SemanticMap)
    np.testing.assert_array_equal(semantic.class_ids, [[0, 4], [9, -1]])
    assert semantic.void_id == -1
    assert semantic.taxonomy is not None
    np.testing.assert_array_equal(semantic.taxonomy.semantic_ids, taxonomy.semantic_ids)
    assert semantic.class_ids.flags.c_contiguous

    instance = sceneio.project_ncore_item(
        _item(
            "instance",
            np.array([[0, 7], [11, 0]], dtype=np.uint16),
            {
                    "instance_background_id": 0,
                "table_instance_ids": [7, 11],
                "table_semantic_ids": [4, 9],
            },
        )
    )
    assert isinstance(instance, InstanceMap)
    np.testing.assert_array_equal(instance.instance_ids, [[0, 7], [11, 0]])
    np.testing.assert_array_equal(instance.table_instance_ids, [7, 11])
    np.testing.assert_array_equal(instance.table_semantic_ids, [4, 9])


def test_ncore_raw_canonical_label_projection_reuses_owned_arrays() -> None:
    source = _item(
        "semantic",
        np.array([[0, 4], [4, -1]], dtype=np.int32),
        {"semantic_void_id": -1},
    )
    valid = np.array([[True, True], [False, True]], dtype=np.bool_)
    item = NCoreItem(
        source.kind,
        source.id,
        {"data": source.array("data"), "valid": valid},
        source.attributes,
    )

    actual = sceneio.project_ncore_item(item)

    assert isinstance(actual, SemanticMap)
    assert np.shares_memory(actual.class_ids, item.array("data"))
    assert np.shares_memory(actual.valid, item.array("valid"))
    assert not actual.class_ids.flags.writeable
    assert not actual.valid.flags.writeable

    expected_class_ids = actual.class_ids.copy()
    expected_valid = actual.valid.copy()
    del item, source, valid
    gc.collect()
    np.testing.assert_array_equal(actual.class_ids, expected_class_ids)
    np.testing.assert_array_equal(actual.valid, expected_valid)


def test_ncore_panoptic_projection_decodes_explicit_divisor() -> None:
    packed = np.array([[0, 4 * 100 + 7], [9 * 100 + 11, 0]], dtype=np.uint16)
    result = sceneio.project_ncore_item(
        _item(
            "panoptic",
            packed,
            {
                "panoptic_label_divisor": 100,
                "semantic_void_id": -1,
                "instance_background_id": 0,
                "table_instance_ids": [7, 11],
                "table_semantic_ids": [4, 9],
            },
        )
    )
    assert isinstance(result, PanopticMap)
    np.testing.assert_array_equal(result.semantic.class_ids, [[0, 4], [9, 0]])
    np.testing.assert_array_equal(result.instance.instance_ids, [[0, 7], [11, 0]])
    np.testing.assert_array_equal(result.instance.table_semantic_ids, [4, 9])


@pytest.mark.parametrize(
    "qualifier",
    ["logits", "custom", "semantic ", "SEMANTIC"],
)
def test_ncore_segmentation_projection_refuses_unknown_qualifier(qualifier: str) -> None:
    item = _item(
        qualifier,
        np.zeros((1, 1), dtype=np.int32),
        {"void_id": -1},
    )
    with pytest.raises(ValueError, match="qualifier"):
        sceneio.project_ncore_item(item)


def test_ncore_segmentation_projection_requires_explicit_meaning() -> None:
    item = _item("semantic", np.array([[0]], dtype=np.int32), {})
    with pytest.raises(ValueError, match="incomplete; missing semantic_void_id"):
        sceneio.project_ncore_item(item)

    malformed = _item(
        "panoptic",
        np.array([[0]], dtype=np.uint16),
        {
            "panoptic_label_divisor": 0,
            "semantic_void_id": -1,
            "instance_background_id": 0,
        },
    )
    with pytest.raises(ValueError, match="divisor"):
        sceneio.project_ncore_item(
            NCoreItem(
                malformed.kind,
                malformed.id,
                malformed.arrays,
                {
                    "descriptor": {
                        **malformed.attributes["descriptor"],
                        "label_type": {
                            "category": "SEGMENTATION",
                            "qualifier": "panoptic",
                            "unit": "UNITLESS",
                        },
                    }
                },
            )
        )


def test_ncore_projection_requires_marker_and_descriptor_ownership() -> None:
    marked = _item(
        "semantic",
        np.array([[0]], dtype=np.int32),
        {"semantic_void_id": -1},
    )
    descriptor = dict(marked.attributes["descriptor"])
    unmarked_descriptor = {
        **descriptor,
        "generic_meta_data": {"semantic_void_id": -1},
    }
    unmarked = NCoreItem(
        marked.kind,
        marked.id,
        marked.arrays,
        {"descriptor": unmarked_descriptor},
    )
    with pytest.raises(ValueError, match="explicit __sceneio_label_map_v1__"):
        sceneio.project_ncore_item(unmarked)

    item_marked = NCoreItem(
        marked.kind,
        marked.id,
        marked.arrays,
        {
            "descriptor": descriptor,
            "generic_meta_data": {
                "__sceneio_label_map_v1__": {
                    "schema": "sceneio.label_map/1",
                    "kind": "semantic",
                    "semantic_void_id": 7,
                }
            },
        },
    )
    with pytest.raises(ValueError, match="must be declared on the descriptor"):
        sceneio.project_ncore_item(item_marked)

    flat = NCoreItem(
        "camera_label",
        "semantic@front",
        {"data": np.zeros((1, 1), dtype=np.int32)},
        {
            "category": "SEGMENTATION",
            "qualifier": "semantic",
            "logical_dtype": "int32",
        },
    )
    with pytest.raises(ValueError, match="requires its complete descriptor"):
        sceneio.project_ncore_item(flat)

    for missing, message in (
        ("camera_id", "requires camera_id"),
        ("label_source", "invalid label_source"),
    ):
        incomplete_descriptor = dict(descriptor)
        del incomplete_descriptor[missing]
        incomplete = NCoreItem(
            marked.kind,
            marked.id,
            marked.arrays,
            {"descriptor": incomplete_descriptor},
        )
        with pytest.raises(ValueError, match=message):
            sceneio.project_ncore_item(incomplete)

    malformed_descriptor = dict(descriptor)
    malformed_descriptor["label_type"] = {
        "category": "SEGMENTATION",
        "qualifier": {"not": "text"},
    }
    malformed_qualifier = NCoreItem(
        marked.kind,
        marked.id,
        marked.arrays,
        {"descriptor": malformed_descriptor},
    )
    with pytest.raises(ValueError, match="qualifier"):
        sceneio.project_ncore_item(malformed_qualifier)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("pixel-unit", "UNITLESS"),
        ("missing-encoding", "missing encoding"),
        ("missing-shape-suffix", "missing shape_suffix"),
        ("unknown-schema-field", "unknown future_semantics"),
    ],
)
def test_ncore_direct_projection_requires_exact_segmentation_descriptor(
    mutation: str,
    message: str,
) -> None:
    source = _item(
        "semantic",
        np.array([[0]], dtype=np.int32),
        {"semantic_void_id": -1},
    )
    descriptor = dict(source.attributes["descriptor"])
    label_type = dict(descriptor["label_type"])
    schema = dict(descriptor["label_schema"])
    attributes: dict[str, object] = {"descriptor": descriptor}
    if mutation == "pixel-unit":
        label_type["unit"] = "PIXELS"
    elif mutation == "missing-encoding":
        del schema["encoding"]
        attributes["encoding"] = "RAW"
    elif mutation == "missing-shape-suffix":
        del schema["shape_suffix"]
    else:
        schema["future_semantics"] = "opaque"
    descriptor["label_type"] = label_type
    descriptor["label_schema"] = schema
    item = NCoreItem(source.kind, source.id, source.arrays, attributes)

    with pytest.raises(ValueError, match=message):
        sceneio.project_ncore_item(item)


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("label_type", "category", {}, "category"),
        ("label_type", "unit", {}, "unit"),
        ("descriptor", "label_source", {}, "source"),
        ("label_schema", "encoding", {}, "encoding"),
        ("label_schema", "dtype", None, "dtype"),
    ],
)
def test_ncore_profile_descriptor_rejects_malformed_json_types(
    section: str,
    field: str,
    value: object,
    message: str,
) -> None:
    descriptor: dict[str, object] = {
        "camera_id": "front",
        "label_type": {
            "category": "SEGMENTATION",
            "qualifier": "semantic",
            "unit": "UNITLESS",
        },
        "label_schema": {
            "dtype": "int32",
            "shape_suffix": [],
            "encoding": "RAW",
            "encoded_format": None,
            "quantization": None,
        },
        "label_source": "GT_SYNTHETIC",
    }
    if section == "descriptor":
        descriptor[field] = value
    else:
        selected = dict(descriptor[section])
        selected[field] = value
        descriptor[section] = selected

    with pytest.raises(ValueError, match=message):
        _label_descriptor(descriptor)


@pytest.mark.parametrize(
    ("qualifier", "metadata"),
    [
        ("semantic", {"semantic_void_id": -1, "future_field": 1}),
        ("semantic", {"semantic_void_id": -1, "instance_background_id": 0}),
        ("semantic", {"semantic_void_id": -1, "panoptic_label_divisor": 100}),
        (
            "instance",
            {
                "instance_background_id": 0,
                "taxonomy_semantic_ids": [0],
            },
        ),
        ("instance", {"instance_background_id": 0, "semantic_void_id": -1}),
    ],
)
def test_ncore_projection_rejects_unknown_or_incompatible_extension_fields(
    qualifier: str,
    metadata: dict[str, object],
) -> None:
    item = _item(qualifier, np.zeros((1, 1), dtype=np.int32), metadata)
    with pytest.raises(ValueError, match="unknown or incompatible fields"):
        sceneio.project_ncore_item(item)


@pytest.mark.parametrize(
    ("data", "declared_dtype", "message"),
    [
        (np.array([[1]], dtype=np.int32), "uint16", "dtype disagrees"),
        (
            np.array([[np.iinfo(np.int32).max + 1]], dtype=np.uint64),
            "uint64",
            "semantic ids exceed int32",
        ),
    ],
)
def test_ncore_semantic_projection_rejects_dtype_and_range_drift(
    data: np.ndarray,
    declared_dtype: str,
    message: str,
) -> None:
    item = _item(
        "semantic",
        data,
        {"semantic_void_id": -1},
        dtype=declared_dtype,
    )
    with pytest.raises(ValueError, match=message):
        sceneio.project_ncore_item(item)


def test_ncore_profile_oracle_preserves_descriptor_before_projection() -> None:
    values = np.array([[0, 4], [9, -1]], dtype=np.int32)
    descriptor = {
        "camera_id": "front",
        "label_type": {
            "category": "SEGMENTATION",
            "qualifier": "semantic",
            "unit": "UNITLESS",
        },
        "label_schema": {
            "dtype": values.dtype.str,
            "shape_suffix": [],
            "encoding": "RAW",
            "encoded_format": None,
            "quantization": None,
        },
        "label_source": "GT_SYNTHETIC",
        "generic_meta_data": {
            "oracle": "manual-ncore-v4-component",
            "__sceneio_label_map_v1__": {
                "schema": "sceneio.label_map/1",
                "kind": "semantic",
                "semantic_void_id": -1,
                "taxonomy_semantic_ids": [0, 4, 9],
                "taxonomy_names": ["background", "vehicle", "pedestrian"],
                "taxonomy_identity": "example.taxonomy",
                "taxonomy_version": "v2",
            },
        },
    }
    component = NCoreComponent(
        "camera_labels",
        "semantic@front",
        "v1",
        "",
        0,
        arrays=(
            NCoreArray("timestamps_us", (1,), "<u8", (1,)),
            NCoreArray("labels/123/data", values.shape, values.dtype.str, values.shape),
        ),
    )
    raw = NCoreComponentData(
        component,
        NCoreSelection("camera_labels", "semantic@front", group=""),
        {
            "timestamps_us": np.array([123], dtype=np.uint64),
            "labels/123/data": values,
        },
        (
            NCoreGroup("", {"component_version": "v1"}),
            NCoreGroup("labels", {"descriptor": descriptor}),
            NCoreGroup(
                "labels/123",
                {"generic_meta_data": {"frame_oracle": 123}},
            ),
        ),
    )

    parsed = read_camera_labels_profile(raw, (100, 200))
    item = parsed.item("camera_label", "123")
    assert item.attributes["descriptor"] == raw.group("labels").attributes[
        "descriptor"
    ]
    assert item.attributes["generic_meta_data"] == {"frame_oracle": 123}
    actual = item.to_sceneio()
    assert isinstance(actual, SemanticMap)
    np.testing.assert_array_equal(actual.class_ids, values)
    assert actual.taxonomy is not None
    assert actual.taxonomy.names == ("background", "vehicle", "pedestrian")


def test_ncore_reverse_component_round_trips_through_existing_writer(tmp_path: Path) -> None:
    taxonomy = _taxonomy()
    expected = SemanticMap(
        np.array([[0, 4], [9, -1]], dtype=np.int32),
        -1,
        taxonomy=taxonomy,
    )
    component = _component_data_from_sceneio_label_map(
        expected,
        instance_name="semantic@front",
        camera_id="front",
        timestamp_us=123,
    )
    dataset = sceneio.NCoreDatasetData(
        sequence_id="sequence-labels",
        timestamp_interval_us=(100, 200),
        generic_metadata={},
        components=(component,),
    )
    destination = tmp_path / "labels"
    sceneio.write_ncore_v4(dataset, destination, storage="directory")
    loaded = sceneio.read_ncore_semantic_component(
        destination,
        NCoreSelection("camera_labels", "semantic@front"),
    )
    actual = loaded.item("camera_label", "123").to_sceneio()
    assert isinstance(actual, SemanticMap)
    np.testing.assert_array_equal(actual.class_ids, expected.class_ids)
    assert actual.void_id == expected.void_id
    assert actual.taxonomy is not None
    assert actual.taxonomy.identity == expected.taxonomy.identity
    assert loaded.item("camera_label", "123").attributes["descriptor"][
        "label_type"
    ]["qualifier"] == "semantic"
    assert loaded.item("camera_label", "123").attributes["descriptor"] == (
        component.group("labels").attributes["descriptor"]
    )


def test_ncore_reverse_panoptic_refuses_background_outside_divisor() -> None:
    value = PanopticMap(
        SemanticMap(np.array([[1]], dtype=np.int32), -1),
        InstanceMap(np.array([[0]], dtype=np.int64), 100),
    )

    with pytest.raises(ValueError, match="0 <= background_id <"):
        _component_data_from_sceneio_label_map(
            value,
            instance_name="panoptic@front",
            camera_id="front",
            timestamp_us=123,
            panoptic_label_divisor=10,
        )


def test_ncore_empty_taxonomy_optional_vectors_round_trip(tmp_path: Path) -> None:
    taxonomy = LabelTaxonomy(
        np.empty(0, dtype=np.int32),
        (),
        "example.empty",
        "v1",
        np.empty((0, 3), dtype=np.uint8),
        np.empty(0, dtype=bool),
    )
    expected = SemanticMap(
        np.full((1, 2), -1, dtype=np.int32),
        -1,
        taxonomy=taxonomy,
    )
    component = _component_data_from_sceneio_label_map(
        expected,
        instance_name="semantic@front",
        camera_id="front",
        timestamp_us=123,
    )
    dataset = sceneio.NCoreDatasetData(
        "sequence-labels",
        (100, 200),
        {},
        (component,),
    )
    destination = tmp_path / "empty-taxonomy"
    sceneio.write_ncore_v4(dataset, destination)

    item = sceneio.read_ncore_semantic_component(
        destination,
        NCoreSelection("camera_labels", "semantic@front"),
    ).item("camera_label", "123")
    actual = item.to_sceneio()
    assert isinstance(actual, SemanticMap)
    assert actual.taxonomy is not None
    assert actual.taxonomy.display_colors.shape == (0, 3)
    assert actual.taxonomy.display_colors.dtype == np.dtype("uint8")
    assert actual.taxonomy.is_thing.shape == (0,)
    assert actual.taxonomy.is_thing.dtype == np.dtype("bool")


def test_ncore_static_mask_projection_remains_boolean() -> None:
    image = np.array([[0, 1], [255, 2]], dtype=np.uint8)
    encoded = bytes(sceneio._core.write_png(sceneio._core.image(image)))
    item = NCoreItem(
        "camera_mask",
        "front/valid",
        {"data": np.array(encoded, dtype=f"|S{len(encoded)}")},
        {"camera_id": "front", "mask_name": "valid", "format": "png"},
    )
    mask = sceneio.project_ncore_item(item)
    np.testing.assert_array_equal(mask.mask, image != 0)
