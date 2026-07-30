from __future__ import annotations

import gc
import tracemalloc
from pathlib import Path

import numpy as np
import pytest
import tinyusdz

import sceneio
from sceneio import _core
from sceneio.io._usd import geometry, stage

_HIERARCHY_USDA = """#usda 1.0
(
    defaultPrim = "World"
    upAxis = "Z"
    metersPerUnit = 0.01
    startTimeCode = 1
    endTimeCode = 5
    timeCodesPerSecond = 30
)
def Xform "World"
{
    uniform token purpose = "render"
    token visibility = "invisible"
    matrix4d xformOp:transform = (
        (1, 0, 0, 2), (0, 1, 0, 3), (0, 0, 1, 4), (0, 0, 0, 1)
    )
    uniform token[] xformOpOrder = ["xformOp:transform"]
    def Xform "Local"
    {
        uniform token[] xformOpOrder = ["!resetXformStack!"]
    }
    def Scope "Guide"
    {
        uniform token purpose = "guide"
    }
}
"""

_MESH_USDA = """#usda 1.0
(
    upAxis = "Y"
    metersPerUnit = 1
)
def Xform "World"
{
    def Mesh "Surface"
    {
        point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        int[] faceVertexCounts = [3]
        int[] faceVertexIndices = [0, 1, 2]
        uniform token subdivisionScheme = "none"
    }
    def Xform "Other"
    {
    }
}
"""


def _hierarchy_scene(**changes):
    transforms = np.broadcast_to(np.eye(4), (3, 4, 4)).copy()
    transforms[0, :3, 3] = [2, 3, 4]
    values = {
        "node_names": ["World", "Local", "Guide"],
        "node_child_offsets": np.array([0, 2, 2, 2], np.uint64),
        "node_children": np.array([1, 2], np.uint64),
        "node_local_transforms": transforms,
        "node_resets_transform_stack": np.array([0, 1, 0], np.uint8),
        "node_visibility": ["invisible", "inherited", "inherited"],
        "node_purpose": ["render", "render", "guide"],
        "up_axis": "z",
        "meters_per_unit": 0.01,
        "source_representation": "usda",
        "default_prim": 0,
        "selected_time": 2.5,
        "start_time_code": 1.0,
        "end_time_code": 5.0,
        "time_codes_per_second": 30.0,
    }
    values.update(changes)
    return _core.scene_graph(**values)


def test_read_scene_maps_hierarchy_metadata_and_selected_static_time(tmp_path):
    path = tmp_path / "hierarchy.usda"
    path.write_text(_HIERARCHY_USDA, encoding="utf-8")

    scene = sceneio.read_scene(
        path,
        time=2.5,
        purposes=("default", "render", "proxy", "guide"),
    )

    assert isinstance(scene, sceneio.SceneGraph)
    assert scene.node_names == ["World", "Local", "Guide"]
    np.testing.assert_array_equal(scene.node_parents, [-1, 0, 0])
    np.testing.assert_array_equal(scene.node_resets_transform_stack, [0, 1, 0])
    np.testing.assert_array_equal(
        scene.node_local_transforms[0, :3, 3],
        [2, 3, 4],
    )
    assert scene.node_visibility == ["invisible", "inherited", "inherited"]
    assert scene.node_purpose == ["render", "render", "guide"]
    assert scene.up_axis == "z"
    assert scene.meters_per_unit == 0.01
    assert scene.source_representation == "usda"
    assert scene.default_prim == 0
    assert scene.selected_time == 2.5
    assert scene.start_time_code == 1.0
    assert scene.end_time_code == 5.0
    assert scene.time_codes_per_second == 30.0


@pytest.mark.parametrize("suffix", [".usda", ".usdz"])
def test_write_scene_hierarchy_cross_reads_and_roundtrips(tmp_path, suffix):
    expected = _hierarchy_scene()
    path = tmp_path / f"hierarchy{suffix}"

    sceneio.write_scene(expected, path)

    oracle = tinyusdz.load(str(path))
    assert oracle.get_metadata("defaultPrim") == "World"
    assert oracle.get_metadata("upAxis") == "Z"
    assert oracle.get_metadata("metersPerUnit") == 0.01
    assert oracle.get_metadata("startTimeCode") == 1.0
    assert oracle.get_metadata("endTimeCode") == 5.0
    assert oracle.get_metadata("timeCodesPerSecond") == 30.0
    actual = sceneio.read_scene(
        path,
        purposes=("default", "render", "proxy", "guide"),
    )
    assert actual.node_names == expected.node_names
    assert actual.node_visibility == expected.node_visibility
    assert actual.node_purpose == expected.node_purpose
    for name in (
        "node_parents",
        "node_child_offsets",
        "node_children",
        "node_local_transforms",
        "node_resets_transform_stack",
    ):
        np.testing.assert_array_equal(
            getattr(actual, name),
            getattr(expected, name),
        )
    assert actual.source_representation == (
        "usdz" if suffix == ".usdz" else "usda"
    )


def test_read_scene_mesh_projection_preserves_legacy_read_contract(tmp_path):
    path = tmp_path / "mesh.usda"
    path.write_text(_MESH_USDA, encoding="utf-8")

    rich = sceneio.read_scene(path)
    legacy = sceneio.read(path)

    assert isinstance(rich, sceneio.SceneGraph)
    assert rich.node_payload_kinds == ["none", "mesh", "none"]
    assert rich.num_meshes == 1
    np.testing.assert_array_equal(
        rich.mesh_at(0).positions,
        [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
    )
    assert isinstance(legacy, sceneio.MeshScene)
    assert legacy.num_primitives == 1


def test_prim_selection_does_not_construct_unselected_payload(
    tmp_path, monkeypatch
):
    path = tmp_path / "selected.usda"
    path.write_text(_MESH_USDA, encoding="utf-8")

    def fail_decode(_prim, **_kwargs):
        raise AssertionError("unselected mesh was decoded")

    monkeypatch.setattr(geometry, "mesh_from_prim", fail_decode)
    selected = sceneio.read_scene(path, prims=("/World/Other",))

    assert selected.node_names == ["World", "Other"]
    assert selected.node_payload_kinds == ["none", "none"]


def test_qualified_historical_usdc_routes_under_usd_codec(tmp_path):
    path = tmp_path / "hierarchy.usdc"
    tinyusdz.loads(
        """#usda 1.0
def Xform "World"
{
}
"""
    ).save(str(path))

    assert path.read_bytes().startswith(b"PXR-USDC\x00")
    assert sceneio.detect(path) == "usd"
    scene = sceneio.read_scene(path)
    assert scene.node_names == ["World"]
    assert scene.source_representation == "usdc"
    inspected = sceneio.inspect(path)
    assert inspected.metadata["representation"] == "usdc"
    assert inspected.metadata["crate_version"] == path.read_bytes()[9]


def test_rich_inspection_reports_stage_metadata_and_projection_boundary(
    tmp_path,
):
    hierarchy = tmp_path / "hierarchy.usda"
    hierarchy.write_text(_HIERARCHY_USDA, encoding="utf-8")

    result = sceneio.inspect(hierarchy)

    assert result.datatype == "mesh_scene"
    assert result.metadata["representation"] == "usda"
    assert result.metadata["up_axis"] == "z"
    assert result.metadata["meters_per_unit"] == 0.01
    assert result.metadata["time_range"] == (1.0, 5.0)
    assert result.metadata["default_prim"] == "World"
    assert result.metadata["prim_type_counts"] == ("Scope=1", "Xform=2")
    assert result.metadata["mesh_projection_available"] is True
    assert result.metadata["unsupported_features"] == ()

    unsupported = tmp_path / "gaussian.usda"
    unsupported.write_text(
        """#usda 1.0
def ParticleField3DGaussianSplat "Cloud"
{
}
""",
        encoding="utf-8",
    )
    report = sceneio.inspect(unsupported)
    assert report.datatype == "scene_graph"
    assert report.metadata["mesh_projection_available"] is False
    assert report.metadata["prim_type_counts"] == (
        "ParticleField3DGaussianSplat=1",
    )
    assert report.metadata["unsupported_features"]


def test_read_scene_record_outlives_removed_source(tmp_path):
    path = tmp_path / "lifetime.usda"
    path.write_text(_HIERARCHY_USDA, encoding="utf-8")
    scene = sceneio.read_scene(path)
    transforms = scene.node_local_transforms

    path.unlink()
    gc.collect()

    np.testing.assert_array_equal(transforms[0, :3, 3], [2, 3, 4])


def test_write_scene_preserves_destination_on_package_failure(
    tmp_path, monkeypatch
):
    path = tmp_path / "preserved.usdz"
    path.write_bytes(b"keep")

    def fail_archive(_source: Path, destination: Path) -> None:
        destination.write_bytes(b"partial")
        raise RuntimeError("injected failure")

    monkeypatch.setattr(stage.package, "write_usdz_archive", fail_archive)
    with pytest.raises(sceneio.FormatError, match="injected failure"):
        sceneio.write_scene(_hierarchy_scene(), path)

    assert path.read_bytes() == b"keep"
    assert list(tmp_path.iterdir()) == [path]


def test_write_scene_refuses_unqualified_usdc_and_unrepresentable_visibility(
    tmp_path,
):
    usdc = tmp_path / "scene.usdc"
    usdc.write_bytes(b"keep")
    with pytest.raises(sceneio.FormatError, match="USDC writing is unavailable"):
        sceneio.write_scene(_hierarchy_scene(), usdc)
    assert usdc.read_bytes() == b"keep"

    visible = tmp_path / "visible.usda"
    visible.write_bytes(b"keep")
    scene = _hierarchy_scene(
        node_visibility=["visible", "inherited", "inherited"]
    )
    with pytest.raises(sceneio.FormatError, match="not visible"):
        sceneio.write_scene(scene, visible)
    assert visible.read_bytes() == b"keep"


def test_read_scene_refuses_time_sample_evaluation_until_provider_support(
    tmp_path,
):
    path = tmp_path / "animated.usda"
    path.write_text(
        """#usda 1.0
def Xform "World"
{
    matrix4d xformOp:transform.timeSamples = {
        1: ((1,0,0,1),(0,1,0,0),(0,0,1,0),(0,0,0,1)),
        2: ((1,0,0,2),(0,1,0,0),(0,0,1,0),(0,0,0,1))
    }
    uniform token[] xformOpOrder = ["xformOp:transform"]
}
""",
        encoding="utf-8",
    )

    with pytest.raises(
        sceneio.FormatError,
        match="selected-time value evaluation is not available",
    ):
        sceneio.read_scene(path, time=1.5)


def test_composition_is_reported_and_refused_without_silent_raw_projection(
    tmp_path,
):
    (tmp_path / "base.usda").write_text(
        """#usda 1.0
def Xform "Referenced"
{
}
""",
        encoding="utf-8",
    )
    path = tmp_path / "reference.usda"
    path.write_text(
        """#usda 1.0
def Xform "World"
{
    def Xform "Arc" (
        references	=	@base.usda@</Referenced>
    )
    {
    }
}
""",
        encoding="utf-8",
    )

    inspected = sceneio.inspect(path)
    assert inspected.datatype == "scene_graph"
    assert inspected.metadata["dependencies"] == ("base.usda",)
    assert "references" in inspected.metadata["unsupported_features"]
    with pytest.raises(
        sceneio.FormatError,
        match=r"evaluated composition.*references",
    ):
        sceneio.read_scene(path)

    benign = tmp_path / "comment-and-string.usda"
    benign.write_text(
        """#usda 1.0
# references = @comment-only.usda@
def Xform "World"
{
    custom string note = "payload = @string-only.usda@"
}
""",
        encoding="utf-8",
    )
    assert stage._scan_authored_features(benign) == (frozenset(), ())


def test_direct_layer_feature_scan_has_bounded_python_allocation(tmp_path):
    path = tmp_path / "large.usda"
    path.write_bytes(b"#usda 1.0\n#" + b"x" * (16 * 1024 * 1024) + b"\n")

    tracemalloc.start()
    try:
        features, dependencies = stage._scan_authored_features(path)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert features == frozenset()
    assert dependencies == ()
    assert peak < 512 * 1024
    renamed = tmp_path / "renamed.usda"
    path.replace(renamed)
    renamed.unlink()


def test_empty_scene_graph_roundtrips(tmp_path):
    path = tmp_path / "empty.usda"

    sceneio.write_scene(_core.scene_graph([]), path)
    actual = sceneio.read_scene(path)

    assert actual.num_nodes == 0
    assert actual.num_meshes == 0
