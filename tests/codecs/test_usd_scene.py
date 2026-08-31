from __future__ import annotations

import gc
from pathlib import Path

import numpy as np
import pytest
import tinyusdz

import sceneio
from sceneio import _core
from sceneio.io._usd import geometry, points, stage
from tests._support.memory_measurement import stable_traced_peak

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


def _rich_geometry_scene(
    *,
    up_axis: str = "y",
    meters_per_unit: float = 1.0,
    display_color_space: str = "linear",
    **changes,
):
    coordinate_frame = "opengl" if up_axis == "y" else "enu"
    mesh = _core.mesh(
        np.array(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
            np.float32,
        ),
        np.array([0, 3], np.uint64),
        np.array([0, 1, 2], np.uint64),
        vertex_normals=np.array(
            [[0, 0, 1], [0, 0, 1], [0, 0, 1]],
            np.float32,
        ),
        corner_uvs=np.array(
            [[0, 0], [1, 0], [0, 1]],
            np.float32,
        ),
        vertex_display_colors=np.array(
            [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            np.float32,
        ),
        corner_display_opacities=np.array(
            [1.0, 0.5, 0.25],
            np.float32,
        ),
        display_color_space=display_color_space,
        coordinate_frame=coordinate_frame,
        scale_to_meters=meters_per_unit,
        orientation="left_handed",
        double_sided=False,
    )
    cloud = _core.point_cloud(
        np.array([[2, 3, 4], [5, 6, 7]], np.float32),
        normals=np.array([[0, 0, 1], [0, 1, 0]], np.float32),
        display_colors=np.array([[0.1, 0.2, 0.3], [1, 1, 1]], np.float32),
        display_opacities=np.array([1.0, 0.4], np.float32),
        widths=np.array([0.1, 0.2], np.float32),
        ids=np.array([10, 20], np.int64),
        velocities=np.array([[1, 0, 0], [0, 1, 0]], np.float32),
        accelerations=np.array([[0, 0, 1], [1, 1, 1]], np.float32),
        display_color_space=display_color_space,
        coordinate_frame=coordinate_frame,
        scale_to_meters=meters_per_unit,
    )
    transforms = np.broadcast_to(np.eye(4), (2, 4, 4)).copy()
    transforms[0, 0, 3] = 2.0
    values = {
        "node_names": ["Surface", "Samples"],
        "node_child_offsets": np.array([0, 0, 0], np.uint64),
        "node_children": np.array([], np.uint64),
        "node_local_transforms": transforms,
        "node_payload_kinds": ["mesh", "point_cloud"],
        "node_payload_indices": np.array([0, 0], np.uint64),
        "meshes": [mesh],
        "point_clouds": [cloud],
        "up_axis": up_axis,
        "meters_per_unit": meters_per_unit,
        "source_representation": "usda",
        "default_prim": 0,
    }
    values.update(changes)
    return _core.scene_graph(**values)


def test_read_scene_maps_hierarchy_metadata_without_false_static_selection(
    tmp_path,
):
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
    assert scene.selected_time is None
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


def test_generic_read_and_read_scene_share_scene_graph_contract(tmp_path):
    path = tmp_path / "mesh.usda"
    path.write_text(_MESH_USDA, encoding="utf-8")

    rich = sceneio.read_scene(path)
    generic = sceneio.read(path)

    assert isinstance(rich, sceneio.SceneGraph)
    assert rich.node_payload_kinds == ["none", "mesh", "none"]
    assert rich.num_meshes == 1
    np.testing.assert_array_equal(
        rich.mesh_at(0).positions,
        [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
    )
    assert isinstance(generic, sceneio.SceneGraph)
    assert generic.node_payload_kinds == rich.node_payload_kinds
    np.testing.assert_array_equal(
        generic.mesh_at(0).positions,
        rich.mesh_at(0).positions,
    )


def test_read_scene_maps_indexed_mesh_and_complete_points_payload(tmp_path):
    path = tmp_path / "geometry.usda"
    path.write_text(
        """#usda 1.0
(
    upAxis = "Y"
    metersPerUnit = 1
)
def Mesh "Surface"
{
    matrix4d xformOp:transform = (
        (1,0,0,2), (0,1,0,0), (0,0,1,0), (0,0,0,1)
    )
    uniform token[] xformOpOrder = ["xformOp:transform"]
    point3f[] points = [(0,0,0), (1,0,0), (0,1,0)]
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0,1,2]
    normal3f[] normals = [(0,0,1), (0,1,0), (0,0,1)] (
        interpolation = "varying"
    )
    color3f[] primvars:displayColor = [(1,0,0), (0,1,0)] (
        interpolation = "vertex"
    )
    int[] primvars:displayColor:indices = [0,1,0]
    float[] primvars:displayOpacity = [1,0.5,0.25] (
        interpolation = "faceVarying"
    )
    uniform token subdivisionScheme = "none"
    uniform token orientation = "leftHanded"
    uniform bool doubleSided = false
}
def Points "Samples"
{
    point3f[] points = [(2,3,4), (5,6,7)]
    normal3f[] normals = [(0,0,1), (0,1,0)] (
        interpolation = "varying"
    )
    float[] widths = [0.2] (
        interpolation = "constant"
    )
    int64[] ids = [10,20]
    vector3f[] velocities = [(1,0,0), (0,1,0)]
    vector3f[] accelerations = [(0,0,1), (1,1,1)]
    color3f[] primvars:displayColor = [(0.1,0.2,0.3)]
    float[] primvars:displayOpacity = [1,0.4] (
        interpolation = "vertex"
    )
}
""",
        encoding="utf-8",
    )

    actual = sceneio.read_scene(path)
    assert actual.node_payload_kinds == ["mesh", "point_cloud"]
    np.testing.assert_array_equal(
        actual.node_local_transforms[0, :3, 3],
        [2, 0, 0],
    )
    mesh = actual.mesh_at(0)
    np.testing.assert_array_equal(
        mesh.vertex_display_colors,
        [[1, 0, 0], [0, 1, 0], [1, 0, 0]],
    )
    np.testing.assert_array_equal(
        mesh.corner_display_opacities,
        [1, 0.5, 0.25],
    )
    assert mesh.display_color_space == "linear"
    assert mesh.orientation == "left_handed"
    assert mesh.has_double_sided and mesh.double_sided is False
    cloud = actual.point_cloud_at(0)
    np.testing.assert_array_equal(cloud.positions, [[2, 3, 4], [5, 6, 7]])
    np.testing.assert_array_equal(
        cloud.widths,
        np.array([0.2, 0.2], np.float32),
    )
    np.testing.assert_array_equal(cloud.ids, [10, 20])
    np.testing.assert_array_equal(
        cloud.display_colors,
        np.array(
            [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]],
            np.float32,
        ),
    )
    np.testing.assert_array_equal(
        cloud.accelerations,
        [[0, 0, 1], [1, 1, 1]],
    )
    assert cloud.display_color_space == "linear"
    assert cloud.coordinate_frame == "opengl"
    assert cloud.scale_to_meters == 1.0

    positions = cloud.positions
    path.unlink()
    del actual, cloud
    gc.collect()
    np.testing.assert_array_equal(positions, [[2, 3, 4], [5, 6, 7]])


@pytest.mark.parametrize("suffix", [".usda", ".usdz"])
def test_write_scene_geometry_cross_reads_and_roundtrips(tmp_path, suffix):
    expected = _rich_geometry_scene()
    path = tmp_path / f"geometry{suffix}"
    duplicate = tmp_path / f"geometry-copy{suffix}"

    sceneio.write_scene(expected, path)
    sceneio.write_scene(expected, duplicate)

    assert path.read_bytes() == duplicate.read_bytes()
    oracle = tinyusdz.load(str(path))
    roots = oracle.root_prims()
    assert [prim.type_name for prim in roots] == ["Mesh", "Points"]
    np.testing.assert_array_equal(
        np.asarray(roots[0].get_attribute("points").value),
        expected.mesh_at(0).positions,
    )
    np.testing.assert_array_equal(
        np.asarray(roots[0].get_attribute("faceVertexCounts").value),
        [3],
    )
    np.testing.assert_array_equal(
        np.asarray(roots[0].get_attribute("faceVertexIndices").value),
        [0, 1, 2],
    )
    assert (
        roots[0].get_attribute_metadata("normals", "interpolation")
        == "vertex"
    )
    assert (
        roots[0].get_attribute_metadata("primvars:st", "interpolation")
        == "faceVarying"
    )
    assert "primvars:displayColor" in roots[0].property_names()
    assert "extent" in roots[0].property_names()
    assert 'uniform token orientation = "leftHanded"' in roots[0].to_string()
    assert "uniform bool doubleSided = 0" in roots[0].to_string()
    point_text = roots[1].to_string()
    assert "float[] widths = [0.1, 0.2]" in point_text
    assert "int64[] ids = [10, 20]" in point_text
    assert "vector3f[] velocities = [(1, 0, 0), (0, 1, 0)]" in point_text
    assert "vector3f[] accelerations = [(0, 0, 1), (1, 1, 1)]" in point_text
    assert "float3[] extent = [(1.95, 2.95, 3.95)," in point_text
    actual = sceneio.read(path)
    assert isinstance(actual, sceneio.SceneGraph)
    assert actual.node_payload_kinds == expected.node_payload_kinds
    np.testing.assert_array_equal(
        actual.node_local_transforms,
        expected.node_local_transforms,
    )
    for name in (
        "positions",
        "vertex_normals",
        "corner_uvs",
        "vertex_display_colors",
        "corner_display_opacities",
    ):
        np.testing.assert_array_equal(
            getattr(actual.mesh_at(0), name),
            getattr(expected.mesh_at(0), name),
        )
    assert actual.mesh_at(0).orientation == "left_handed"
    assert actual.mesh_at(0).double_sided is False
    for name in (
        "positions",
        "normals",
        "display_colors",
        "display_opacities",
        "widths",
        "ids",
        "velocities",
        "accelerations",
    ):
        np.testing.assert_array_equal(
            getattr(actual.point_cloud_at(0), name),
            getattr(expected.point_cloud_at(0), name),
        )


def test_mesh_domains_defaults_and_indexed_uniform_values(tmp_path):
    path = tmp_path / "domains.usda"
    path.write_text(
        """#usda 1.0
(
    upAxis = "Y"
    metersPerUnit = 1
)
def Mesh "Surface"
{
    point3f[] points = [(0,0,0), (1,0,0), (1,1,0), (0,1,0)]
    int[] faceVertexCounts = [3,3]
    int[] faceVertexIndices = [0,1,2,0,2,3]
    normal3f[] normals = [(1,0,0), (1,0,0), (1,0,0), (1,0,0)]
    normal3f[] primvars:normals = [(0,0,1)] (
        interpolation = "vertex"
    )
    int[] primvars:normals:indices = [0,0,0,0]
    texCoord2f[] primvars:st = [(0.25,0.75)]
    color3f[] primvars:displayColor = [(1,0,0), (0,1,0)] (
        interpolation = "uniform"
    )
    float[] primvars:displayOpacity = [0.25,1] (
        interpolation = "uniform"
    )
    int[] primvars:displayOpacity:indices = [1,0]
    float3[] extent = [(-1,-1,-1), (2,2,1)]
    uniform token subdivisionScheme = "none"
}
""",
        encoding="utf-8",
    )

    mesh = sceneio.read_scene(path).mesh_at(0)

    np.testing.assert_array_equal(
        mesh.vertex_normals,
        np.tile(np.array([[0, 0, 1]], np.float32), (4, 1)),
    )
    np.testing.assert_array_equal(
        mesh.vertex_uvs,
        np.tile(np.array([[0.25, 0.75]], np.float32), (4, 1)),
    )
    np.testing.assert_array_equal(
        mesh.corner_display_colors,
        np.array(
            [[1, 0, 0]] * 3 + [[0, 1, 0]] * 3,
            np.float32,
        ),
    )
    np.testing.assert_array_equal(
        mesh.corner_display_opacities,
        np.array([1, 1, 1, 0.25, 0.25, 0.25], np.float32),
    )


def test_points_primvar_widths_take_precedence_over_builtin_widths(tmp_path):
    path = tmp_path / "width-precedence.usda"
    path.write_text(
        """#usda 1.0
(
    upAxis = "Y"
    metersPerUnit = 1
)
def Points "Samples"
{
    point3f[] points = [(0,0,0), (1,1,1)]
    normal3f[] normals = [(1,0,0), (1,0,0)]
    normal3f[] primvars:normals = [(0,1,0), (0,0,1)] (
        interpolation = "vertex"
    )
    int[] primvars:normals:indices = [1,0]
    float[] widths = [9,9] (interpolation = "vertex")
    float[] primvars:widths = [0.4]
    int[] primvars:widths:indices = [0]
}
""",
        encoding="utf-8",
    )

    cloud = sceneio.read_scene(path).point_cloud_at(0)

    np.testing.assert_array_equal(
        cloud.widths,
        np.array([0.4, 0.4], np.float32),
    )
    np.testing.assert_array_equal(
        cloud.normals,
        np.array([[0, 0, 1], [0, 1, 0]], np.float32),
    )


def test_srgb_display_fields_author_and_roundtrip_color_space(tmp_path):
    expected = _rich_geometry_scene(display_color_space="srgb")
    path = tmp_path / "srgb.usda"

    sceneio.write_scene(expected, path)

    text = path.read_text(encoding="utf-8")
    assert text.count('colorSpace = "srgb_rec709_scene"') == 2
    actual = sceneio.read_scene(path)
    assert actual.mesh_at(0).display_color_space == "srgb"
    assert actual.point_cloud_at(0).display_color_space == "srgb"


def test_empty_mesh_and_points_payloads_roundtrip(tmp_path):
    mesh = _core.mesh(
        np.empty((0, 3), np.float32),
        np.array([0], np.uint64),
        np.empty(0, np.uint64),
        coordinate_frame="opengl",
    )
    cloud = _core.point_cloud(
        np.empty((0, 3), np.float32),
        coordinate_frame="opengl",
    )
    scene = _rich_geometry_scene(meshes=[mesh], point_clouds=[cloud])
    path = tmp_path / "empty-geometry.usda"

    sceneio.write_scene(scene, path)
    actual = sceneio.read_scene(path)

    assert actual.mesh_at(0).num_vertices == 0
    assert actual.mesh_at(0).num_faces == 0
    assert actual.point_cloud_at(0).num_points == 0


def test_z_up_geometry_preserves_coordinates_and_payload_conventions(tmp_path):
    expected = _rich_geometry_scene(up_axis="z", meters_per_unit=0.01)
    path = tmp_path / "z-up.usda"

    sceneio.write_scene(expected, path)
    actual = sceneio.read_scene(path)

    assert actual.up_axis == "z"
    assert actual.meters_per_unit == 0.01
    assert actual.mesh_at(0).coordinate_frame == "enu"
    assert actual.point_cloud_at(0).coordinate_frame == "enu"
    assert actual.mesh_at(0).scale_to_meters == 0.01
    assert actual.point_cloud_at(0).scale_to_meters == 0.01
    np.testing.assert_array_equal(
        actual.mesh_at(0).positions,
        expected.mesh_at(0).positions,
    )
    np.testing.assert_array_equal(
        actual.point_cloud_at(0).positions,
        expected.point_cloud_at(0).positions,
    )


def test_points_inspection_and_selection_do_not_construct_records(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "geometry.usda"
    sceneio.write_scene(_rich_geometry_scene(), path)

    def fail_factory(*_args, **_kwargs):
        raise AssertionError("inspection decoded a point payload")

    monkeypatch.setattr(points._core, "point_cloud", fail_factory)
    monkeypatch.setattr(points, "point_arrays_from_prim", fail_factory)
    inspected = sceneio.inspect(path)
    assert inspected.datatype == "scene_graph"
    assert inspected.metadata["prim_type_counts"] == (
        "Mesh=1",
        "Points=1",
    )
    assert inspected.metadata["primitive_count"] == 2
    assert inspected.shape == (5, 3)

    selected = sceneio.read_scene(path, prims=("/Surface",))
    assert selected.node_names == ["Surface"]
    assert selected.node_payload_kinds == ["mesh"]

    skipped = tmp_path / "skip-unselected-points.usda"
    skipped.write_text(
        """#usda 1.0
(
    upAxis = "Y"
    metersPerUnit = 1
)
def Xform "Keep"
{
}
def Points "Skip"
{
    point3f[] points = [(0, 0, 0)]
    custom float providerOnly = 1
}
""",
        encoding="utf-8",
    )
    selected = sceneio.read_scene(skipped, prims=("/Keep",))
    assert selected.node_names == ["Keep"]
    with pytest.raises(sceneio.FormatError, match="providerOnly"):
        sceneio.read_scene(skipped)


def test_geometry_guards_preserve_destinations_and_refuse_bad_domains(tmp_path):
    malformed = (
        (
            """def Points "P" {
    point3f[] points = [(0,0,0), (1,1,1)]
    int64[] ids = [1]
}""",
            "ids.*count",
        ),
        (
            """def Points "P" {
    point3f[] points = [(0,0,0), (1,1,1)]
    float[] widths = [1, 2] (interpolation = "uniform")
}""",
            "widths.*interpolation/count",
        ),
        (
            """def Mesh "M" {
    point3f[] points = [(0,0,0), (1,0,0), (0,1,0)]
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0,1,2]
    color3f[] primvars:displayColor = [(1,0,0), (0,1,0)] (
        interpolation = "uniform"
    )
    uniform token subdivisionScheme = "none"
}""",
            "displayColor # of items|uniform count",
        ),
        (
            """def Mesh "M" {
    point3f[] points = [(0,0,0), (1,0,0), (0,1,0)]
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0,1,2]
    int[] primvars:st:indices = [0]
    uniform token subdivisionScheme = "none"
}""",
            "primvars:st:indices.*requires",
        ),
        (
            """def Points "P" {
    point3f[] points = [(0,0,0)]
    int[] primvars:displayColor:indices = [0]
}""",
            "primvars:displayColor:indices.*requires",
        ),
        (
            """def Mesh "M" {
    point3f[] points = [(0,0,0), (1,0,0), (0,1,0)]
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0,1,2]
}""",
            "subdivisionScheme must be authored",
        ),
        (
            """def Mesh "M" {
    point3f[] points = [(0,0,0), (1,0,0), (0,1,0)]
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0,1,2]
    float3[] extent = [(0,0,0), (0.5,1,0)]
    uniform token subdivisionScheme = "none"
}""",
            "extent does not enclose points",
        ),
        (
            """def Points "P" {
    point3f[] points = [(0,0,0)]
    float[] widths = [2]
    float3[] extent = [(0,0,0), (1,1,1)]
}""",
            "extent does not enclose points and widths",
        ),
        (
            """def Points "P" {
    point3f[] points = [(0,0,0), (1,1,1)]
    int64[] ids = [7,7]
}""",
            "ids must be unique",
        ),
        (
            """def Points "P" {
    point3f[] points = [(0,0,0)]
    float[] primvars:displayOpacity = [1.5]
}""",
            r"display opacity must be in \[0, 1\]",
        ),
        (
            """def Points "P" {
    point3f[] points = [(0,0,0)]
    color3f[] primvars:displayColor = [(1,0,0)] (
        colorSpace = "acescg"
    )
}""",
            "unsupported colorSpace",
        ),
        (
            """def Points "P" {
    point3f[] points = [(0,0,0)]
    float3[] extent = [(1,1,1), (0,0,0)]
}""",
            "extent minimum exceeds maximum",
        ),
        (
            """def Mesh "M" {
    point3f[] points = [(0,0,0), (1,0,0), (0,1,0)]
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0,1,3]
    uniform token subdivisionScheme = "none"
}""",
            "vertexIndex2 3 exceeds|face index is outside",
        ),
        (
            """def Mesh "M" {
    point3f[] points = [(0,0,0), (1,0,0), (0,1,0)]
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0,1,2]
    float[] primvars:displayOpacity = [1,2,1] (
        interpolation = "vertex"
    )
    uniform token subdivisionScheme = "none"
}""",
            r"display opacity must be in \[0, 1\]",
        ),
        (
            """def Mesh "M" {
    point3f[] points = [(0,0,0), (1,0,0), (0,1,0)]
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0,1,2]
    float[] primvars:displayOpacity = [0.5] (
        unauthoredValuesIndex = 0
    )
    uniform token subdivisionScheme = "none"
}""",
            "unauthoredValuesIndex must be -1",
        ),
        (
            """def Points "P" {
    point3f[] points = [(0,0,0)]
    float[] primvars:widths = [0.1,0.2] (
        elementSize = 2
    )
}""",
            "elementSize must be 1",
        ),
        (
            """def Mesh "M" {
    point3f[] points = [(0,0,0), (1,0,0), (0,1,0)]
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0,1,2]
    color3f[] primvars:displayColor = [(1,0,0)] (
        interpolation = "vertex"
    )
    int[] primvars:displayColor:indices = [0,1,0]
    uniform token subdivisionScheme = "none"
}""",
            "Failed to flatten primvar|indices.*out of range",
        ),
        (
            """def Mesh "M" {
    point3f[] points = [(0,0,0), (1,0,0), (0,1,0)]
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0,1,2]
    uniform token orientation = "sideways"
    uniform token subdivisionScheme = "none"
}""",
            "invalid authored orientation",
        ),
        (
            """def Mesh "M" {
    point3f[] points = [(0,0,0), (1,0,0), (0,1,0)]
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0,1,2]
    float3[] primvars:normals = [(0,0,1)] (
        interpolation = "constant"
    )
    uniform token subdivisionScheme = "none"
}""",
            "primvars:normals.*normal3f",
        ),
        (
            """def Mesh "M" {
    point3f[] points = [(0,0,0), (1,0,0), (0,1,0)]
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0,1,2]
    float2[] primvars:st = [(0,0)] (
        interpolation = "constant"
    )
    uniform token subdivisionScheme = "none"
}""",
            "primvars:st.*texCoord2f",
        ),
        (
            """def Mesh "M" {
    point3f[] points = [(0,0,0), (1,0,0), (0,1,0)]
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0,1,2]
    vector3f[] primvars:displayColor = [(1,0,0)] (
        interpolation = "constant"
    )
    uniform token subdivisionScheme = "none"
}""",
            "primvars:displayColor.*color3f",
        ),
        (
            """def Points "P" {
    point3f[] points = [(0,0,0)]
    float3[] primvars:normals = [(0,0,1)] (
        interpolation = "vertex"
    )
}""",
            "primvars:normals.*normal3f",
        ),
        (
            """def Points "P" {
    point3f[] points = [(0,0,0)]
    vector3f[] primvars:displayColor = [(1,0,0)] (
        interpolation = "vertex"
    )
}""",
            "primvars:displayColor.*color3f",
        ),
        (
            """def Mesh "M" {
    point3f[] points = [(0,0,0), (1,0,0), (0,1,0)]
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0,1,2]
    float[] primvars:displayOpacity = [0.5,2] (
        interpolation = "vertex"
    )
    int[] primvars:displayOpacity:indices = [0,0,0]
    uniform token subdivisionScheme = "none"
}""",
            r"display opacity must be in \[0, 1\]",
        ),
        (
            """def Points "P" {
    point3f[] points = [(1e40,0,0)]
}""",
            "Failed to parse floating|points.*finite",
        ),
        (
            """def Points "P" {
    point3f[] points.timeSamples = {
        1: [(0,0,0)],
        2: [(1,1,1)]
    }
}""",
            "time-varying properties.*points",
        ),
    )
    for index, (body, message) in enumerate(malformed):
        path = tmp_path / f"bad-{index}.usda"
        path.write_text(
            '#usda 1.0\n( upAxis = "Y" metersPerUnit = 1 )\n' + body,
            encoding="utf-8",
        )
        with pytest.raises(sceneio.FormatError, match=message):
            sceneio.read_scene(path)
        try:
            inspected = sceneio.inspect(path)
        except sceneio.FormatError:
            assert "1e40" in body
        else:
            assert inspected.metadata["unsupported_features"]

    metadata_decoys = (
        """def Mesh "M" {
    point3f[] points = [(0,0,0), (1,0,0), (0,1,0)]
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0,1,2]
    float[] primvars:displayOpacity = [0.5] (
        interpolation = "constant"
        customData = {
            string note = "elementSize = 2"
        }
    )
    uniform token subdivisionScheme = "none"
}""",
        """def Points "P" {
    point3f[] points = [(0,0,0)]
    float[] primvars:widths = [0.1] (
        interpolation = "vertex"
        customData = {
            string note = "unauthoredValuesIndex = 0"
        }
    )
}""",
    )
    for index, body in enumerate(metadata_decoys):
        path = tmp_path / f"metadata-decoy-{index}.usda"
        path.write_text(
            '#usda 1.0\n( upAxis = "Y" metersPerUnit = 1 )\n' + body,
            encoding="utf-8",
        )
        sceneio.read_scene(path)
        assert sceneio.inspect(path).metadata["unsupported_features"] == ()

    cloud = _core.point_cloud(
        np.zeros((1, 3), np.float32),
        colors=np.zeros((1, 3), np.uint8),
        coordinate_frame="opengl",
    )
    invalid = _rich_geometry_scene(point_clouds=[cloud])
    destination = tmp_path / "preserved.usda"
    destination.write_bytes(b"sentinel")
    with pytest.raises(
        sceneio.FormatError,
        match="quantized color/intensity",
    ):
        sceneio.write_scene(invalid, destination)
    assert destination.read_bytes() == b"sentinel"

    dual_mesh = _core.mesh(
        np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32),
        np.array([0, 3], np.uint64),
        np.array([0, 1, 2], np.uint64),
        vertex_normals=np.tile(np.array([[0, 0, 1]], np.float32), (3, 1)),
        corner_normals=np.tile(np.array([[0, 0, 1]], np.float32), (3, 1)),
        coordinate_frame="opengl",
    )
    dual = _rich_geometry_scene(meshes=[dual_mesh])
    with pytest.raises(sceneio.FormatError, match="both vertex and corner"):
        sceneio.write_scene(dual, destination)
    assert destination.read_bytes() == b"sentinel"


@pytest.mark.parametrize("suffix", [".usda", ".usdz"])
def test_geometry_views_outlive_scene_provider_and_source(tmp_path, suffix):
    path = tmp_path / f"owned{suffix}"
    sceneio.write_scene(_rich_geometry_scene(), path)
    scene = sceneio.read_scene(path)
    mesh_positions = scene.mesh_at(0).positions
    mesh_normals = scene.mesh_at(0).vertex_normals
    point_widths = scene.point_cloud_at(0).widths
    point_ids = scene.point_cloud_at(0).ids

    path.unlink()
    del scene
    gc.collect()

    np.testing.assert_array_equal(mesh_positions[1], [1, 0, 0])
    np.testing.assert_array_equal(mesh_normals[0], [0, 0, 1])
    np.testing.assert_array_equal(
        point_widths,
        np.array([0.1, 0.2], np.float32),
    )
    np.testing.assert_array_equal(point_ids, [10, 20])


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

    assert result.datatype == "scene_graph"
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
    assert report.metadata["unsupported_features"] == ()
    assert report.metadata["num_gaussian_clouds"] == 1


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

    def fail_archive(
        _source: Path,
        destination: Path,
        *,
        assets=(),
    ) -> None:
        tuple(assets)
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


def test_read_scene_evaluates_qualified_matrix_samples(
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

    actual = sceneio.read_scene(path, time=1.5)
    np.testing.assert_array_equal(
        actual.node_local_transforms[0, :3, 3],
        [1.5, 0, 0],
    )
    assert actual.selected_time == 1.5
    inspected = sceneio.inspect(path)
    assert inspected.metadata["provider_selected_time"] is True
    assert "/World: time_samples" in inspected.metadata["unsupported_features"]


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
    assert inspected.metadata["profile"] == "sceneio.usd.3dcv/1"
    assert inspected.metadata["provider_current_usdc"] is False
    assert inspected.metadata["provider_composition"] is False
    assert inspected.metadata["provider_selected_time"] is True
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
    custom string subLayers = "plain"
    custom string references = "plain"
    custom string payload = "plain"
    custom string variantSet = "plain"
    custom string variants = "plain"
    custom string inherits = "plain"
    custom string specializes = "plain"
    custom string bindMaterialAs = "plain"
}
""",
        encoding="utf-8",
    )
    assert stage._scan_authored_features(benign) == (frozenset(), ())


@pytest.mark.parametrize(
    ("feature", "body"),
    [
        ("sublayers", '( subLayers = [@base.usda@] )'),
        (
            "references",
            'def Xform "Arc" ( prepend references = @base.usda@</Base> ) {}',
        ),
        (
            "payloads",
            'def Xform "Arc" ( payload = @base.usda@</Base> ) {}',
        ),
        (
            "variants",
            '''def Xform "Arc" (
    variants = { string model = "A" }
    prepend variantSets = "model"
)
{
    variantSet "model" = { "A" { def Xform "Chosen" {} } }
}''',
        ),
        (
            "inherits",
            'def Xform "Arc" ( inherits = </Base> ) {}',
        ),
        (
            "specializes",
            'def Xform "Arc" ( specializes = </Base> ) {}',
        ),
    ],
    ids=(
        "sublayers",
        "references",
        "payloads",
        "variants",
        "inherits",
        "specializes",
    ),
)
def test_direct_profile_reports_and_refuses_composition_arcs(
    tmp_path, feature, body
):
    (tmp_path / "base.usda").write_text(
        '#usda 1.0\ndef Xform "Base" {}\n', encoding="utf-8"
    )
    path = tmp_path / f"{feature}.usda"
    path.write_text(f"#usda 1.0\n{body}\n", encoding="utf-8")

    inspected = sceneio.inspect(path)
    assert feature in inspected.metadata["unsupported_features"]
    assert inspected.metadata["provider_composition"] is False
    with pytest.raises(
        sceneio.FormatError,
        match=rf"evaluated composition.*{feature}",
    ):
        sceneio.read_scene(path)


def test_direct_layer_feature_scan_has_bounded_python_allocation(tmp_path):
    path = tmp_path / "large.usda"
    path.write_bytes(b"#usda 1.0\n#" + b"x" * (16 * 1024 * 1024) + b"\n")

    (features, dependencies), peak = stable_traced_peak(
        lambda: stage._scan_authored_features(path)
    )

    assert features == frozenset()
    assert dependencies == ()
    assert peak < 512 * 1024
    renamed = tmp_path / "renamed.usda"
    path.replace(renamed)
    renamed.unlink()

    indented = tmp_path / "indented.usda"
    indented.write_bytes(
        b"#usda 1.0\n("
        + b" " * (4 * 1024 * 1024)
        + b"references = @base.usda@</Base>\n)\n"
    )
    (features, dependencies), peak = stable_traced_peak(
        lambda: stage._scan_authored_features(indented)
    )
    assert features == frozenset({"references"})
    assert dependencies == ("base.usda",)
    assert peak < 512 * 1024


def test_empty_scene_graph_roundtrips(tmp_path):
    path = tmp_path / "empty.usda"

    sceneio.write_scene(_core.scene_graph([]), path)
    actual = sceneio.read_scene(path)

    assert actual.num_nodes == 0
    assert actual.num_meshes == 0
