from __future__ import annotations

import gc

import numpy as np
import pytest

import sceneio
from sceneio import _core

tinyusdz = pytest.importorskip("tinyusdz")

_INSTANCE_STAGE = '''#usda 1.0
def Xform "Root"
{
    def PointInstancer "Copies"
    {
        rel prototypes = [</Root/PrototypeB>, </Root/PrototypeA>]
        int[] protoIndices = [0, 1, 0]
        int64[] ids = [10, 20, 30]
        int64[] invisibleIds = [20]
        point3f[] positions = [(1, 2, 3), (4, 5, 6), (7, 8, 9)]
        quatf[] orientationsf = [
            (1, 0, 0, 0),
            (0, 1, 0, 0),
            (0.5, 0.5, 0.5, 0.5)
        ]
        float3[] scales = [(1, 1, 1), (2, 2, 2), (0.5, 0.5, 0.5)]
        vector3f[] velocities = [(1, 0, 0), (0, 1, 0), (0, 0, 1)]
        color3f[] primvars:displayColor = [
            (1, 0, 0), (0, 1, 0), (0, 0, 1)
        ] (
            interpolation = "instance"
        )
    }
    def Xform "PrototypeA" {}
    def Xform "PrototypeB" {}
}
'''


def _write(path, text: str = _INSTANCE_STAGE):
    path.write_text(text, encoding="utf-8")
    return path


def _instance_scene():
    attributes = _core.tensor_dict(
        {
            "velocities": np.eye(3, dtype=np.float32),
            "display_opacities": np.array([1.0, 0.5, 0.0], np.float32),
        }
    )
    value = _core.instance_set(
        np.array([2, 1], np.uint64),
        np.array([0, 1, 0], np.uint64),
        np.arange(9, dtype=np.float32).reshape(3, 3),
        orientations=np.array(
            [[1, 0, 0, 0], [0, 1, 0, 0], [0.5, 0.5, 0.5, 0.5]],
            np.float32,
        ),
        scales=np.array(
            [[1, 1, 1], [2, 2, 2], [0.5, 0.5, 0.5]],
            np.float32,
        ),
        ids=np.array([10, 20, 30], np.int64),
        invisible_ids=np.array([20], np.int64),
        attributes=attributes,
    )
    return _core.scene_graph(
        ["Copies", "PrototypeA", "PrototypeB"],
        node_payload_kinds=["instances", "none", "none"],
        node_payload_indices=np.array(
            [0, np.iinfo(np.uint64).max, np.iinfo(np.uint64).max],
            np.uint64,
        ),
        instances=[value],
    )


def test_point_instancer_preserves_order_ids_transforms_and_attributes(tmp_path):
    scene = sceneio.read_scene(_write(tmp_path / "instances.usda"))
    value = scene.instance_set_at(0)

    assert scene.node_payload_kinds == ["none", "instances", "none", "none"]
    assert [scene.node_names[index] for index in value.prototype_nodes] == [
        "PrototypeB",
        "PrototypeA",
    ]
    np.testing.assert_array_equal(value.prototype_indices, [0, 1, 0])
    np.testing.assert_array_equal(value.ids, [10, 20, 30])
    np.testing.assert_array_equal(value.invisible_ids, [20])
    np.testing.assert_array_equal(value.invisible_mask, [0, 1, 0])
    np.testing.assert_array_equal(value.translations[2], [7, 8, 9])
    np.testing.assert_array_equal(value.attributes["velocities"], np.eye(3))
    np.testing.assert_array_equal(
        value.attributes["display_colors"], np.eye(3)
    )

    positions = value.translations
    del value, scene
    gc.collect()
    np.testing.assert_array_equal(positions[:, 0], [1, 4, 7])


def test_selected_instancer_adds_prototype_dependencies(tmp_path):
    scene = sceneio.read_scene(
        _write(tmp_path / "selected.usda"),
        prims="/Root/Copies",
    )
    value = scene.instance_set_at(0)

    assert scene.node_names == ["Root", "Copies", "PrototypeA", "PrototypeB"]
    assert [scene.node_names[index] for index in value.prototype_nodes] == [
        "PrototypeB",
        "PrototypeA",
    ]


def test_point_instancer_writer_is_oracle_readable_and_roundtrips(tmp_path):
    destination = tmp_path / "instances.usda"

    sceneio.write_scene(_instance_scene(), destination)

    text = destination.read_text(encoding="utf-8")
    assert "rel prototypes = [</PrototypeB>, </PrototypeA>]" in text
    assert 'interpolation = "instance"' in text
    oracle = tinyusdz.load(str(destination))
    assert [prim.type_name for prim in tinyusdz.traverse(oracle)].count(
        "PointInstancer"
    ) == 1
    decoded = sceneio.read_scene(destination)
    actual = decoded.instance_set_at(0)
    np.testing.assert_array_equal(actual.prototype_indices, [0, 1, 0])
    np.testing.assert_array_equal(actual.ids, [10, 20, 30])
    np.testing.assert_array_equal(
        actual.attributes["display_opacities"], [1.0, 0.5, 0.0]
    )


def test_inspection_counts_instances_without_expanding_prototypes(tmp_path):
    inspected = sceneio.inspect(_write(tmp_path / "inspect.usda"))

    assert inspected.metadata["num_instance_sets"] == 1
    assert inspected.metadata["num_instances"] == 3
    assert inspected.metadata["num_instance_prototypes"] == 2
    assert inspected.count == 1


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        (
            'def PointInstancer "Copies" (\n        inactiveIds = [20]\n    )',
            "inactiveIds",
        ),
        (
            "rel prototypes = [</Root/Missing>, </Root/PrototypeA>]",
            "does not name a scene prim",
        ),
    ],
)
def test_unrepresentable_instance_metadata_and_missing_prototype_are_refused(
    tmp_path,
    replacement,
    message,
):
    if replacement.startswith("def"):
        text = _INSTANCE_STAGE.replace('def PointInstancer "Copies"', replacement)
    else:
        text = _INSTANCE_STAGE.replace(
            "rel prototypes = [</Root/PrototypeB>, </Root/PrototypeA>]",
            replacement,
        )
    path = _write(tmp_path / "unsupported.usda", text)

    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.read_scene(path)


def test_prototype_cycle_is_refused_by_read_and_reported_by_inspection(
    tmp_path,
):
    path = _write(
        tmp_path / "cycle.usda",
        '''#usda 1.0
def PointInstancer "A"
{
    rel prototypes = [</B>]
    int[] protoIndices = [0]
    point3f[] positions = [(0, 0, 0)]
}
def PointInstancer "B"
{
    rel prototypes = [</A>]
    int[] protoIndices = [0]
    point3f[] positions = [(0, 0, 0)]
}
''',
    )

    with pytest.raises(sceneio.FormatError, match=r"prototype graph.*cycle"):
        sceneio.read_scene(path)
    inspected = sceneio.inspect(path)
    assert any(
        "prototype graph contains a cycle" in item
        for item in inspected.metadata["unsupported_features"]
    )


def test_unsupported_instance_attribute_preserves_destination(tmp_path):
    value = _core.instance_set(
        np.array([1], np.uint64),
        np.array([0], np.uint64),
        np.zeros((1, 3), np.float32),
        attributes=_core.tensor_dict(
            {"temperature": np.array([20.0], np.float32)}
        ),
    )
    scene = _core.scene_graph(
        ["Copies", "Prototype"],
        node_payload_kinds=["instances", "none"],
        node_payload_indices=np.array(
            [0, np.iinfo(np.uint64).max], np.uint64
        ),
        instances=[value],
    )
    destination = tmp_path / "keep.usda"
    destination.write_bytes(b"keep")

    with pytest.raises(sceneio.FormatError, match="temperature"):
        sceneio.write_scene(scene, destination)

    assert destination.read_bytes() == b"keep"
