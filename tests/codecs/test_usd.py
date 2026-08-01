from __future__ import annotations

import gc
import struct
import zipfile
from pathlib import Path

import numpy as np
import pytest
import tinyusdz

import sceneio
from sceneio import _core
from sceneio.io import _usd


def _fixture():
    positions = np.array(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
        dtype=np.float32,
    )
    face_offsets = np.array([0, 3, 6], dtype=np.uint64)
    face_indices = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint64)
    normals = np.tile(
        np.array([[0, 0, 1]], dtype=np.float32), (len(positions), 1)
    )
    uv_bits = np.array(
        [
            0x00000000,
            0x80000000,
            0x3F000001,
            0x3F800000,
            0x40000000,
            0x40400000,
            0x40800000,
            0x40A00000,
            0x40C00000,
            0x40E00000,
            0x41000000,
            0x41100000,
        ],
        dtype=np.uint32,
    )
    corner_uvs = uv_bits.view(np.float32).reshape(6, 2)
    mesh = _core.mesh(
        positions,
        face_offsets,
        face_indices,
        vertex_normals=normals,
        corner_uvs=corner_uvs,
        coordinate_frame="opengl",
    )
    transforms = np.tile(np.eye(4, dtype=np.float64), (2, 1, 1))
    transforms[0, :3, 3] = [2.5, -3.25, 4.125]
    scene = _core.mesh_scene(
        [mesh],
        np.array([0, 1], dtype=np.uint64),
        node_meshes=np.array([-1, 0], dtype=np.int64),
        node_child_offsets=np.array([0, 1, 1], dtype=np.uint64),
        node_children=np.array([1], dtype=np.uint64),
        node_local_transforms=transforms,
        node_names=["World", "Surface"],
        scene_root_offsets=np.array([0, 1], dtype=np.uint64),
        scene_roots=np.array([0], dtype=np.uint64),
        default_scene=0,
    )
    return scene


def _assert_mesh_equal(actual, expected):
    for name in (
        "positions",
        "face_offsets",
        "face_indices",
        "vertex_normals",
        "corner_uvs",
    ):
        left = np.asarray(getattr(actual, name))
        right = np.asarray(getattr(expected, name))
        assert left.dtype == right.dtype
        assert left.shape == right.shape
        assert left.tobytes() == right.tobytes()
    assert actual.coordinate_frame == expected.coordinate_frame
    assert actual.scale_to_meters == expected.scale_to_meters


def _assert_scene_equal(actual, expected):
    assert actual.num_meshes == expected.num_meshes
    assert actual.num_primitives == expected.num_primitives
    assert actual.num_nodes == expected.num_nodes
    assert actual.num_scenes == expected.num_scenes
    assert actual.default_scene == expected.default_scene
    assert list(actual.node_names) == list(expected.node_names)
    for name in (
        "mesh_primitive_offsets",
        "node_meshes",
        "node_child_offsets",
        "node_children",
        "node_local_transforms",
        "scene_root_offsets",
        "scene_roots",
    ):
        left = np.asarray(getattr(actual, name))
        right = np.asarray(getattr(expected, name))
        assert left.dtype == right.dtype
        assert left.shape == right.shape
        assert left.tobytes() == right.tobytes()
    for index in range(actual.num_primitives):
        _assert_mesh_equal(
            actual.primitive_at(index), expected.primitive_at(index)
        )


@pytest.mark.parametrize("suffix", [".usd", ".usda", ".usdz"])
def test_usd_registry_roundtrip_is_bit_exact(tmp_path, suffix):
    expected = _fixture()
    path = tmp_path / f"scene{suffix}"

    sceneio.write(expected, path)
    actual = sceneio.read(path)

    assert sceneio.detect(path) == ("usdz" if suffix == ".usdz" else "usd")
    _assert_scene_equal(actual, expected)


@pytest.mark.parametrize("suffix", [".usd", ".usdz"])
def test_sceneio_usd_writer_is_readable_by_upstream_oracle(tmp_path, suffix):
    scene = _fixture()
    path = tmp_path / f"oracle{suffix}"

    sceneio.write(scene, path)

    stage = tinyusdz.load(str(path))
    assert stage.get_metadata("upAxis") == "Y"
    assert stage.get_metadata("metersPerUnit") == 1.0
    meshes = [
        prim for prim in tinyusdz.traverse(stage) if prim.type_name == "Mesh"
    ]
    assert len(meshes) == 1
    mesh = meshes[0]
    np.testing.assert_array_equal(
        np.asarray(mesh.get_attribute("points").value),
        np.asarray(scene.primitive_at(0).positions),
    )
    np.testing.assert_array_equal(
        np.asarray(mesh.get_attribute("faceVertexCounts").value),
        np.array([3, 3], np.int32),
    )
    np.testing.assert_array_equal(
        np.asarray(mesh.get_attribute("faceVertexIndices").value),
        np.asarray(scene.primitive_at(0).face_indices).astype(np.int32),
    )
    rendered = tinyusdz.tydra.convert_to_render_scene(stage)
    assert [(node.abs_path, node.name) for node in rendered.nodes()] == [
        ("/World", "World")
    ]


def test_sceneio_reads_upstream_written_binary_usdz(tmp_path):
    source = """#usda 1.0
(
    upAxis = "Y"
    metersPerUnit = 1
)
def Xform "World"
{
    def Mesh "Triangle"
    {
        point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        int[] faceVertexCounts = [3]
        int[] faceVertexIndices = [0, 1, 2]
        uniform token subdivisionScheme = "none"
    }
}
"""
    stage = tinyusdz.loads(source)
    path = tmp_path / "upstream.usdz"
    stage.save(str(path))

    scene = sceneio.read(path)

    assert list(scene.node_names) == ["World", "Triangle"]
    assert np.asarray(scene.node_meshes).tolist() == [-1, 0]
    mesh = scene.primitive_at(0)
    np.testing.assert_array_equal(
        np.asarray(mesh.positions),
        np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32),
    )


def test_usdz_package_is_uncompressed_and_64_byte_aligned(tmp_path):
    path = tmp_path / "aligned.usdz"
    sceneio.write(_fixture(), path)

    raw = path.read_bytes()
    name_length, extra_length = struct.unpack_from("<HH", raw, 26)
    data_offset = 30 + name_length + extra_length
    with zipfile.ZipFile(path) as archive:
        assert archive.namelist() == ["root.usda"]
        assert archive.getinfo("root.usda").compress_type == zipfile.ZIP_STORED
        assert archive.read("root.usda").startswith(b"#usda 1.0\n")
    assert data_offset % 64 == 0


@pytest.mark.parametrize("suffix", [".usd", ".usdz"])
def test_usd_record_outlives_removed_source(tmp_path, suffix):
    path = tmp_path / f"lifetime{suffix}"
    sceneio.write(_fixture(), path)

    decoded = sceneio.read(path)
    path.unlink()
    gc.collect()

    np.testing.assert_array_equal(
        np.asarray(decoded.primitive_at(0).positions),
        np.asarray(_fixture().primitive_at(0).positions),
    )


@pytest.mark.parametrize("suffix", [".usd", ".usdz"])
def test_usd_inspection_matches_decoded_scene(tmp_path, suffix):
    path = tmp_path / f"inspect{suffix}"
    sceneio.write(_fixture(), path)

    result = sceneio.inspect(path)

    assert result.format == ("usdz" if suffix == ".usdz" else "usd")
    assert result.datatype == "mesh_scene"
    assert result.shape == (4, 3)
    assert result.dtype == "float32"
    assert result.count == 1
    assert result.metadata == {
        "node_count": 2,
        "primitive_count": 1,
        "face_count": 2,
        "scene_count": 1,
        "representation": "usdz" if suffix == ".usdz" else "usda",
        "up_axis": "y",
        "meters_per_unit": 1.0,
        "time_codes_per_second": 24.0,
        "mesh_projection_available": True,
        "prim_type_counts": ("Mesh=1", "Xform=1"),
        "dependencies": (),
        "variants": (),
        "unsupported_features": (),
        "num_materials": 0,
        "num_textures": 0,
    }


def test_usd_inspection_does_not_construct_mesh_scene(tmp_path, monkeypatch):
    path = tmp_path / "inspect.usd"
    sceneio.write(_fixture(), path)

    def fail_full_decode(_stage):
        raise AssertionError("inspection must not build a MeshScene")

    monkeypatch.setattr(_usd.legacy, "_stage_to_scene", fail_full_decode)

    assert sceneio.inspect(path).shape == (4, 3)


def test_usd_reader_refuses_non_cv_stage_conventions(tmp_path):
    path = tmp_path / "z_up.usda"
    path.write_text(
        """#usda 1.0
(
    upAxis = "Z"
    metersPerUnit = 0.01
)
def Xform "World"
{
}
""",
        encoding="utf-8",
    )

    with pytest.raises(
        sceneio.FormatError, match=r"upAxis='Y'.*metersPerUnit=1"
    ):
        sceneio.read(path)


def test_usd_reader_refuses_subdivision_surfaces(tmp_path):
    path = tmp_path / "subdivision.usda"
    path.write_text(
        """#usda 1.0
(
    upAxis = "Y"
    metersPerUnit = 1
)
def Mesh "Surface"
{
    point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    int[] faceVertexCounts = [3]
    int[] faceVertexIndices = [0, 1, 2]
    uniform token subdivisionScheme = "catmullClark"
}
""",
        encoding="utf-8",
    )

    with pytest.raises(sceneio.FormatError, match="subdivision surfaces"):
        sceneio.read(path)


@pytest.mark.parametrize(("suffix", "version"), [(".usd", 11), (".usdz", 12)])
def test_usd_reader_refuses_unqualified_usdc_versions_before_provider(
    tmp_path, monkeypatch, suffix, version
):
    crate = b"PXR-USDC\x00" + bytes([version]) + b"unread"
    path = tmp_path / f"future{suffix}"
    if suffix == ".usdz":
        root = tmp_path / "root.usdc"
        root.write_bytes(crate)
        _usd.package.write_usdz_archive(root, path)
    else:
        path.write_bytes(crate)

    def fail_load(*_args, **_kwargs):
        raise AssertionError("unqualified crate reached the provider")

    monkeypatch.setattr(tinyusdz, "load", fail_load)
    with pytest.raises(
        sceneio.FormatError,
        match=rf"crate version {version}.*qualified maximum version 10",
    ):
        sceneio.read(path, format="usdz" if suffix == ".usdz" else "usd")


def test_usd_writer_refuses_transform_on_mesh_node(tmp_path):
    source = _fixture()
    transforms = np.array(source.node_local_transforms, copy=True)
    transforms[0] = np.eye(4)
    transforms[1, 0, 3] = 1
    scene = _core.mesh_scene(
        [source.primitive_at(0)],
        np.array(source.mesh_primitive_offsets, copy=True),
        node_meshes=np.array(source.node_meshes, copy=True),
        node_child_offsets=np.array(source.node_child_offsets, copy=True),
        node_children=np.array(source.node_children, copy=True),
        node_local_transforms=transforms,
        node_names=list(source.node_names),
        scene_root_offsets=np.array(source.scene_root_offsets, copy=True),
        scene_roots=np.array(source.scene_roots, copy=True),
        default_scene=0,
    )

    with pytest.raises(sceneio.FormatError, match="mesh-referencing nodes"):
        sceneio.write(scene, tmp_path / "invalid.usd")


def test_usd_existing_destination_survives_package_failure(
    tmp_path, monkeypatch
):
    path = tmp_path / "preserved.usdz"
    path.write_bytes(b"keep")

    def fail(source, destination):
        destination.write_bytes(b"partial")
        raise RuntimeError("injected failure")

    monkeypatch.setattr(_usd.legacy, "_write_usdz_archive", fail)
    with pytest.raises(RuntimeError, match="injected failure"):
        sceneio.write_usdz(_fixture(), path)

    assert path.read_bytes() == b"keep"
    assert list(tmp_path.iterdir()) == [path]


def test_tinyusdz_license_is_distributed():
    text = (
        Path(__file__).parents[2] / "LICENSES" / "tinyusdz.txt"
    ).read_text(encoding="utf-8")
    assert "Apache 2.0 License" in text
    assert "Light Transport Entertainment Inc." in text
