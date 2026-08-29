from __future__ import annotations

import gc

import numpy as np
import pytest

import sceneio
from sceneio import _core

pytest.importorskip("tinyusdz")


def _write(path, body: str):
    path.write_text("#usda 1.0\n" + body, encoding="utf-8")
    return path


def _semantic_scene(*, child_label: str = "vehicle"):
    return _core.scene_graph(
        ["Root", "Child"],
        node_child_offsets=np.array([0, 1, 1], np.uint64),
        node_children=np.array([1], np.uint64),
        node_semantic_taxonomies=["class", "class" if child_label else ""],
        node_semantic_labels=["vehicle", child_label],
    )


def test_semantic_label_inheritance_is_evaluated_per_node(tmp_path):
    path = _write(
        tmp_path / "labels.usda",
        '''def Xform "Root" (
    prepend apiSchemas = ["SemanticsLabelsAPI:class"]
)
{
    token[] semantics:labels:class = ["vehicle"]
    def Xform "Child" {}
}
''',
    )

    scene = sceneio.read_scene(path)

    assert scene.node_semantic_taxonomies == ["class", "class"]
    assert scene.node_semantic_labels == ["vehicle", "vehicle"]
    inspected = sceneio.inspect(path)
    assert inspected.metadata["num_semantic_nodes"] == 2

    labels = scene.node_semantic_labels
    del scene
    gc.collect()
    assert labels == ["vehicle", "vehicle"]


@pytest.mark.parametrize(
    "body",
    [
        '''def Xform "Root" (
    prepend apiSchemas = ["SemanticsLabelsAPI:class"]
)
{
    token[] semantics:labels:class = ["vehicle", "moving"]
}
''',
        '''def Xform "Root" (
    prepend apiSchemas = [
        "SemanticsLabelsAPI:class",
        "SemanticsLabelsAPI:domain"
    ]
)
{
    token[] semantics:labels:class = ["vehicle"]
    token[] semantics:labels:domain = ["road"]
}
''',
    ],
)
def test_multiple_evaluated_semantic_values_are_refused(tmp_path, body):
    path = _write(tmp_path / "multiple.usda", body)

    with pytest.raises(
        sceneio.FormatError, match=r"multiple (labels|taxonomies)"
    ):
        sceneio.read_scene(path)


def test_semantic_write_is_minimal_and_roundtrips(tmp_path):
    source = _semantic_scene()
    path = tmp_path / "labels.usda"

    sceneio.write_scene(source, path)

    text = path.read_text(encoding="utf-8")
    assert text.count("SemanticsLabelsAPI:class") == 1
    assert text.count("semantics:labels:class") == 1
    decoded = sceneio.read_scene(path)
    assert decoded.node_semantic_taxonomies == ["class", "class"]
    assert decoded.node_semantic_labels == ["vehicle", "vehicle"]


def test_unrepresentable_semantic_clear_preserves_destination(tmp_path):
    destination = tmp_path / "keep.usda"
    destination.write_bytes(b"keep")

    with pytest.raises(sceneio.FormatError, match="cannot clear or replace"):
        sceneio.write_scene(_semantic_scene(child_label=""), destination)

    assert destination.read_bytes() == b"keep"
