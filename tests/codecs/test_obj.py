"""Independent parity, fidelity, lifetime, and edge tests for OBJ/MTL."""

from __future__ import annotations

import gc
import locale
import mmap
import os
import tracemalloc

import numpy as np
import pytest
import trimesh

import sceneio
from sceneio import _core


def _fixture() -> tuple[bytes, bytes]:
    obj = b"""# independent polygonal fixture
mtllib materials.mtl
o main\\ object
g front
v 0 0 0 1 0 0
v 1 0 0 0 1 0
v 1 1 0 0 0 1
v 0 1 0 1 1 1
v 0 0 1 0.5019608 0.2509804 0
vt 0 0
vt 1 0
vt 1 1
vt 0 1
vt 0.25 0.25
vt 0.5 0.75
vt 0.75 0.5
vn 0 0 1
vn 1 0 0
usemtl matte
s 7
f 1/1/1 2/2/1 3/3/1 4/4/1
o cap
g rear
usemtl glass
s off
f -5/5/2 -2/6/2 -1/7/2
"""
    mtl = b"""# independent strict-subset fixture
newmtl matte
Kd 0.25 0.5 0.75
Ke 2 1 0.5
Pm 0.4
Pr 0.6
d 1
map_Kd -clamp on textures/albedo\\ map.png
map_Ka ambient.png
map_Ks specular.png
map_Ns shininess.png
norm normal.png
disp displacement.exr
map_d alpha.png
map_Ke emissive.exr
map_Pm metallic.png
map_Pr roughness.png
refl reflection.hdr

newmtl glass
Kd 0.8 0.9 1
Tr 0.25
"""
    return obj, mtl


def _materials():
    return _core.material_set(
        ["matte", "glass"],
        base_colors=np.array(
            [[0.25, 0.5, 0.75, 1.0], [0.8, 0.9, 1.0, 0.5]],
            np.float32,
        ),
        emissive_colors=np.array([[2, 1, 0.5], [0, 0, 0]], np.float32),
        metallic=np.array([0.4, 0], np.float32),
        roughness=np.array([0.6, 1], np.float32),
        alpha_modes=["opaque", "blend"],
        texture_materials=np.array([0, 0, 1], np.uint64),
        texture_semantics=["normal", "base_color", "roughness"],
        texture_paths=["normal.png", "albedo map.png", "roughness.png"],
        texture_uv_sets=np.zeros(3, np.uint32),
        texture_wrap_s=["clamp", "repeat", "repeat"],
        texture_wrap_t=["clamp", "repeat", "repeat"],
    )


def _mesh(*, corner_domain: bool = True):
    positions = np.array(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1]],
        np.float32,
    )
    kwargs = {
        "vertex_colors": np.array(
            [
                [255, 0, 0, 255],
                [0, 255, 0, 255],
                [0, 0, 255, 255],
                [255, 255, 255, 255],
                [128, 64, 0, 255],
            ],
            np.uint8,
        ),
        "primitive_offsets": np.array([0, 1, 2], np.uint64),
        "primitive_materials": np.array([0, 1], np.int32),
        "face_smoothing_groups": np.array([7, 0], np.uint32),
        "primitive_object_names": ["main object", "cap"],
        "primitive_group_names": ["front", "rear"],
        "materials": _materials(),
    }
    if corner_domain:
        kwargs["corner_normals"] = np.array(
            [[0, 0, 1]] * 4 + [[1, 0, 0]] * 3, np.float32
        )
        kwargs["corner_uvs"] = np.array(
            [
                [0, 0],
                [1, 0],
                [1, 1],
                [0, 1],
                [0.25, 0.25],
                [0.5, 0.75],
                [0.75, 0.5],
            ],
            np.float32,
        )
    else:
        kwargs["vertex_normals"] = np.array([[0, 0, 1]] * 5, np.float32)
        kwargs["vertex_uvs"] = np.array(
            [[0, 0], [1, 0], [1, 1], [0, 1], [0.5, 0.5]], np.float32
        )
    return _core.mesh(
        positions,
        np.array([0, 4, 7], np.uint64),
        np.array([0, 1, 2, 3, 0, 3, 4], np.uint64),
        **kwargs,
    )


def _assert_materials_equal(left, right):
    assert left.names == right.names
    assert left.alpha_modes == right.alpha_modes
    assert left.texture_semantics == right.texture_semantics
    assert left.texture_paths == right.texture_paths
    for name in (
        "base_colors",
        "emissive_colors",
        "metallic",
        "roughness",
        "alpha_cutoffs",
        "texture_materials",
        "texture_uv_sets",
        "texture_wrap_s_codes",
        "texture_wrap_t_codes",
        "texture_min_filter_codes",
        "texture_mag_filter_codes",
    ):
        np.testing.assert_array_equal(getattr(left, name), getattr(right, name))


def _assert_mesh_equal(left, right):
    assert type(left) is type(right) is _core.Mesh
    for name in (
        "positions",
        "face_offsets",
        "face_indices",
        "vertex_normals",
        "corner_normals",
        "vertex_uvs",
        "corner_uvs",
        "vertex_colors",
        "corner_colors",
        "primitive_offsets",
        "primitive_materials",
        "face_smoothing_groups",
        "local_transform",
    ):
        np.testing.assert_array_equal(getattr(left, name), getattr(right, name))
    assert left.coordinate_frame == right.coordinate_frame
    assert left.scale_to_meters == right.scale_to_meters
    assert left.primitive_object_names == right.primitive_object_names
    assert left.primitive_group_names == right.primitive_group_names
    assert left.has_materials == right.has_materials
    if left.has_materials:
        _assert_materials_equal(left.materials, right.materials)


def test_independent_fixture_preserves_polygon_and_all_supported_domains():
    obj, mtl = _fixture()
    mesh = _core.read_obj(obj, mtl)

    np.testing.assert_array_equal(
        mesh.positions,
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1]],
    )
    assert mesh.face_offsets.tolist() == [0, 4, 7]
    assert mesh.face_indices.tolist() == [0, 1, 2, 3, 0, 3, 4]
    assert mesh.vertex_normals.shape == (0, 3)
    np.testing.assert_array_equal(
        mesh.corner_normals, [[0, 0, 1]] * 4 + [[1, 0, 0]] * 3
    )
    np.testing.assert_array_equal(
        mesh.corner_uvs,
        [
            [0, 0],
            [1, 0],
            [1, 1],
            [0, 1],
            [0.25, 0.25],
            [0.5, 0.75],
            [0.75, 0.5],
        ],
    )
    np.testing.assert_array_equal(
        mesh.vertex_colors,
        [
            [255, 0, 0, 255],
            [0, 255, 0, 255],
            [0, 0, 255, 255],
            [255, 255, 255, 255],
            [128, 64, 0, 255],
        ],
    )
    assert mesh.primitive_offsets.tolist() == [0, 1, 2]
    assert mesh.primitive_materials.tolist() == [0, 1]
    assert mesh.face_smoothing_groups.tolist() == [7, 0]
    assert mesh.primitive_object_names == ["main object", "cap"]
    assert mesh.primitive_group_names == ["front", "rear"]
    assert mesh.materials.names == ["matte", "glass"]
    np.testing.assert_array_equal(
        mesh.materials.base_colors,
        np.array(
            [[0.25, 0.5, 0.75, 1], [0.8, 0.9, 1, 0.75]], np.float32
        ),
    )
    assert mesh.materials.alpha_modes == ["opaque", "blend"]
    assert mesh.materials.texture_semantics == [
        "base_color",
        "ambient",
        "specular",
        "specular_highlight",
        "normal",
        "displacement",
        "alpha",
        "emissive",
        "metallic",
        "roughness",
        "reflection",
    ]
    assert mesh.materials.texture_paths[0] == "textures/albedo map.png"
    assert mesh.materials.texture_wrap_s_codes.tolist()[0] == 1


def test_vertex_aligned_indices_decode_to_vertex_domain_with_unused_vertex():
    data = b"""v 0 0 0
v 1 0 0
v 0 1 0
v 9 9 9
vt 0 0
vt 1 0
vt 0 1
vt 0.5 0.5
vn 0 0 1
vn 0 0 1
vn 0 0 1
vn 1 0 0
f 1/1/1 2/2/2 3/3/3
"""
    mesh = _core.read_obj(data)
    assert mesh.vertex_uvs.shape == (4, 2)
    assert mesh.vertex_normals.shape == (4, 3)
    assert mesh.corner_uvs.shape == (0, 2)
    assert mesh.corner_normals.shape == (0, 3)
    np.testing.assert_array_equal(mesh.vertex_uvs[-1], [0.5, 0.5])
    np.testing.assert_array_equal(mesh.vertex_normals[-1], [1, 0, 0])


@pytest.mark.parametrize("corner_domain", [False, True])
def test_deterministic_writer_roundtrips_every_representable_field(corner_domain):
    expected = _mesh(corner_domain=corner_domain)
    obj = bytes(_core.write_obj(expected, "scene materials.mtl"))
    mtl = bytes(_core.write_mtl(expected.materials))
    assert obj == bytes(_core.write_obj(expected, "scene materials.mtl"))
    assert mtl == bytes(_core.write_mtl(expected.materials))
    assert b"mtllib scene\\ materials.mtl\n" in obj
    assert b"f 1/1/1 2/2/2 3/3/3 4/4/4\n" in obj
    actual = _core.read_obj(obj, mtl)
    _assert_mesh_equal(actual, expected)


def test_writer_is_independent_of_process_numeric_locale():
    previous = locale.setlocale(locale.LC_NUMERIC)
    candidates = (
        "German_Germany.1252",
        "de-DE",
        "de_DE.UTF-8",
        "de_DE.utf8",
        "French_France.1252",
        "fr-FR",
        "fr_FR.UTF-8",
    )
    try:
        for candidate in candidates:
            try:
                locale.setlocale(locale.LC_NUMERIC, candidate)
            except locale.Error:
                continue
            if locale.localeconv()["decimal_point"] != ".":
                break
        else:
            pytest.skip("no comma-decimal numeric locale is installed")

        expected = _mesh(corner_domain=False)
        obj = bytes(_core.write_obj(expected, "materials.mtl"))
        mtl = bytes(_core.write_mtl(expected.materials))
        assert b"," not in obj
        assert b"," not in mtl
        actual = _core.read_obj(obj, mtl)
    finally:
        locale.setlocale(locale.LC_NUMERIC, previous)

    _assert_mesh_equal(actual, expected)


def test_simple_output_is_accepted_by_trimesh_oracle(tmp_path):
    mesh = _core.mesh(
        np.array([[0, 0, 0], [2, 0, 0], [0, 3, 0]], np.float32),
        np.array([0, 3], np.uint64),
        np.array([0, 1, 2], np.uint64),
    )
    path = tmp_path / "triangle.obj"
    path.write_bytes(bytes(_core.write_obj(mesh)))
    oracle = trimesh.load(path, force="mesh", process=False, maintain_order=True)
    np.testing.assert_allclose(oracle.vertices, mesh.positions)
    np.testing.assert_array_equal(oracle.faces, [[0, 1, 2]])


def test_trimesh_export_is_accepted_without_triangulation_loss():
    oracle = trimesh.Trimesh(
        vertices=np.array([[0, 0, 0], [2, 0, 0], [0, 3, 0]], np.float64),
        faces=np.array([[0, 1, 2]], np.int64),
        process=False,
    )
    data = trimesh.exchange.obj.export_obj(
        oracle, include_normals=False, include_color=False
    ).encode()
    actual = _core.read_obj(data)
    np.testing.assert_allclose(actual.positions, oracle.vertices)
    np.testing.assert_array_equal(actual.face_indices, oracle.faces.reshape(-1))
    assert actual.face_offsets.tolist() == [0, 3]


def test_buffer_protocol_mmap_differential_lifetime_and_mutation_isolation(
    tmp_path,
):
    obj, mtl = _fixture()
    obj_path = tmp_path / "fixture.obj"
    mtl_path = tmp_path / "materials.mtl"
    obj_path.write_bytes(obj)
    mtl_path.write_bytes(mtl)
    expected = _core.read_obj(obj, mtl)

    with (
        obj_path.open("rb") as obj_file,
        mtl_path.open("rb") as mtl_file,
        mmap.mmap(obj_file.fileno(), 0, access=mmap.ACCESS_READ) as obj_map,
        mmap.mmap(mtl_file.fileno(), 0, access=mmap.ACCESS_READ) as mtl_map,
    ):
        actual = _core.read_obj(obj_map, mtl_map)
        position_view = actual.positions
    obj_path.write_bytes(b"")
    mtl_path.write_bytes(b"")
    gc.collect()
    _assert_mesh_equal(actual, expected)
    np.testing.assert_array_equal(position_view, expected.positions)

    from_memoryviews = _core.read_obj(memoryview(obj), memoryview(mtl))
    _assert_mesh_equal(from_memoryviews, expected)


def test_core_inspection_and_material_library_scan_without_decode():
    obj, mtl = _fixture()
    assert _core.obj_material_library(obj) == "materials.mtl"
    assert _core.inspect_obj(obj) == {
        "num_vertices": 5,
        "num_faces": 2,
        "num_corners": 7,
        "num_normals": 2,
        "num_texcoords": 7,
        "has_vertex_colors": True,
        "has_smoothing_groups": True,
        "material_library": "materials.mtl",
    }
    assert _core.inspect_mtl(mtl) == {
        "num_materials": 2,
        "num_textures": 11,
    }
    assert _core.obj_material_library(b"v 0 0 0\n") is None


def test_public_detect_read_write_inspect_and_capabilities(tmp_path):
    obj, mtl = _fixture()
    source = tmp_path / "fixture.obj"
    (tmp_path / "materials.mtl").write_bytes(mtl)
    source.write_bytes(obj)

    assert sceneio.detect(source) == "obj"
    _assert_mesh_equal(sceneio.read(source), _core.read_obj(obj, mtl))
    info = sceneio.inspect(source)
    assert info.format == "obj"
    assert info.payload_kind == "mesh"
    assert info.shape == (5, 3)
    assert info.dtype == "float32"
    assert info.count == 5
    assert info.byte_size == len(obj) + len(mtl)
    assert dict(info.metadata) == {
        "num_faces": 2,
        "num_corners": 7,
        "num_normals": 2,
        "num_texcoords": 7,
        "has_vertex_colors": True,
        "has_smoothing_groups": True,
        "material_library": "materials.mtl",
        "num_materials": 2,
        "num_textures": 11,
    }

    destination = tmp_path / "written.obj"
    expected = _mesh()
    sceneio.write(expected, destination)
    assert (tmp_path / "written.mtl").is_file()
    assert b"mtllib written.mtl\n" in destination.read_bytes()
    _assert_mesh_equal(sceneio.read(destination), expected)
    capabilities = sceneio.capabilities("obj")
    assert capabilities.container_kind == "multi_file"
    assert capabilities.streams_read
    assert capabilities.streams_write
    assert capabilities.partial_selectors == ()
    assert "polygon_boundaries" in capabilities.supported_features


def test_public_single_file_obj_and_empty_fallback(tmp_path):
    mesh = _core.mesh(
        np.empty((0, 3), np.float32),
        np.array([0], np.uint64),
        np.empty(0, np.uint64),
    )
    path = tmp_path / "empty.obj"
    sceneio.write(mesh, path)
    assert not (tmp_path / "empty.mtl").exists()
    _assert_mesh_equal(sceneio.read(path), mesh)

    path.write_bytes(b"")
    decoded = sceneio.read(path)
    assert decoded.num_vertices == decoded.num_faces == 0


def test_public_errors_preserve_existing_obj_and_mtl_destinations(tmp_path):
    path = tmp_path / "preserved.obj"
    mtl_path = tmp_path / "preserved.mtl"
    path.write_bytes(b"old obj")
    mtl_path.write_bytes(b"old mtl")
    invalid = _rebuild_mesh(_mesh(), coordinate_frame="opencv")
    with pytest.raises(sceneio.FormatError, match="coordinate frame"):
        sceneio.write(invalid, path)
    assert path.read_bytes() == b"old obj"
    assert mtl_path.read_bytes() == b"old mtl"
    assert not list(tmp_path.glob("*.sceneio-*.tmp"))

    missing = tmp_path / "missing.obj"
    missing.write_bytes(b"mtllib absent.mtl\n")
    with pytest.raises(sceneio.FormatError, match=r"absent\.mtl"):
        sceneio.read(missing)
    absolute = tmp_path / "absolute.obj"
    absolute.write_bytes(b"mtllib C:/absolute/materials.mtl\n")
    with pytest.raises(sceneio.FormatError, match="must be relative"):
        sceneio.read(absolute)


def test_paired_output_install_failure_restores_both_destinations(
    tmp_path, monkeypatch
):
    from sceneio.io import _obj as obj_adapter

    path = tmp_path / "rollback.obj"
    mtl_path = tmp_path / "rollback.mtl"
    path.write_bytes(b"old obj")
    mtl_path.write_bytes(b"old mtl")
    real_replace = obj_adapter.os.replace
    failed = False

    def fail_obj_publication(source, destination):
        nonlocal failed
        source = obj_adapter.Path(source)
        destination = obj_adapter.Path(destination)
        if (
            not failed
            and destination == path
            and source.name.startswith(".rollback.obj.sceneio-")
        ):
            failed = True
            raise OSError("injected OBJ publication failure")
        return real_replace(source, destination)

    monkeypatch.setattr(obj_adapter.os, "replace", fail_obj_publication)
    with pytest.raises(
        sceneio.FormatError, match="injected OBJ publication failure"
    ):
        sceneio.write(_mesh(), path)
    assert failed
    assert path.read_bytes() == b"old obj"
    assert mtl_path.read_bytes() == b"old mtl"
    assert not list(tmp_path.glob("*.sceneio-*.tmp"))


def test_public_mmap_read_avoids_whole_file_python_bytes(tmp_path):
    path = tmp_path / "large.obj"
    path.write_bytes(
        b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
        + b"# provenance padding\n" * 70_000
    )
    size = path.stat().st_size
    assert size > 1_000_000
    sceneio.read(path)
    gc.collect()

    tracemalloc.start()
    data = path.read_bytes()
    _core.read_obj(data)
    _, bytes_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del data

    tracemalloc.start()
    sceneio.read(path)
    _, mmap_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert bytes_peak >= size * 0.8
    assert mmap_peak < size * 0.1


def test_generated_100mb_obj_mmap_avoids_whole_file_python_copy(tmp_path):
    path = tmp_path / "generated-large.obj"
    comment = b"#" + b"x" * (1024 * 1024 - 1) + b"\n"
    with path.open("wb") as stream:
        stream.write(b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
        for _ in range(101):
            stream.write(comment)
    assert path.stat().st_size > 100 * 1024 * 1024

    tracemalloc.start()
    try:
        mesh = sceneio.read(path)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert mesh.num_vertices == 3
    assert mesh.num_faces == 1
    assert peak < 4 * 1024 * 1024


def test_public_sink_avoids_output_sized_python_bytes(tmp_path):
    positions = np.random.default_rng(401).standard_normal((120_000, 3)).astype(
        np.float32
    )
    mesh = _core.mesh(
        positions,
        np.array([0], np.uint64),
        np.empty(0, np.uint64),
    )
    path = tmp_path / "large.obj"
    tracemalloc.start()
    try:
        sceneio.write(mesh, path)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert path.stat().st_size > 4_000_000
    assert peak < path.stat().st_size / 8


@pytest.mark.parametrize(
    ("obj", "mtl", "message"),
    [
        (b"q unsupported\n", None, "unsupported directive"),
        (b"v 0 0 0\nl 1\n", None, "unsupported directive"),
        (b"v 0 0 0\nv 1 0 0\nf 1 2\n", None, "at least three"),
        (
            b"v 0 0 0\nv 1 0 0 1 1 1\n",
            None,
            "mixed colored",
        ),
        (
            b"v 0 0 0 0.501961 0 0\n",
            None,
            "exactly representable",
        ),
        (b"g one two\n", None, "multiple simultaneous groups"),
        (
            b"mtllib a.mtl\nmtllib b.mtl\n",
            b"",
            "only one material",
        ),
        (b"mtllib a.mtl\n", None, "was not supplied"),
        (b"v 0 0 0\n", b"newmtl a\n", "without mtllib"),
        (
            b"mtllib a.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
            b"usemtl missing\nf 1 2 3\n",
            b"newmtl present\n",
            "unknown material",
        ),
        (
            b"v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\n"
            b"f 1/1 2 3\n",
            None,
            "mixed present/missing corner UV",
        ),
        (
            b"v 0 0 0\nv 1 0 0\nv 0 1 0\nvn 0 0 1\n"
            b"f 1//1 2 3\n",
            None,
            "mixed present/missing corner normal",
        ),
        (
            b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 4\n",
            None,
            "indic",
        ),
        (
            b"v 0 0 0\nv 1 0 0\nv 0 1 0\nvn 0 0 1\n"
            b"vn 1 0 0\nf 1//1 2//1 3//1\n",
            None,
            "unreferenced normal",
        ),
        (
            b"v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\n"
            b"vt 1 0\nf 1/1 2/1 3/1\n",
            None,
            "unreferenced texture",
        ),
        (b"v nan 0 0\n", None, "invalid or out-of-range"),
        (b"v 0 0 0\x00\n", None, "embedded NUL"),
        (b"v 0 0 \xff\n", None, "UTF-8"),
        (b"o " + b"a" * (1024 * 1024 + 1), None, "1 MiB"),
    ],
    ids=[
        "unknown-directive",
        "line-primitive",
        "short-face",
        "mixed-vertex-color",
        "inexact-vertex-color",
        "multiple-groups",
        "multiple-mtllib",
        "missing-mtl-input",
        "extraneous-mtl-input",
        "unknown-material",
        "mixed-uv-index",
        "mixed-normal-index",
        "vertex-index-range",
        "unreferenced-normal",
        "unreferenced-uv",
        "nonfinite-position",
        "embedded-nul",
        "invalid-utf8",
        "line-limit",
    ],
)
def test_obj_malformed_or_unrepresentable_inputs_reject(obj, mtl, message):
    with pytest.raises(ValueError, match=message):
        _core.read_obj(obj, mtl)


@pytest.mark.parametrize(
    ("mtl", "message"),
    [
        (b"Kd 1 1 1\n", "before newmtl"),
        (b"newmtl a\nnewmtl a\n", "unique"),
        (b"newmtl a\nKa 1 1 1\n", "unsupported fidelity"),
        (b"newmtl a\nKd 2 1 1\n", "out-of-range"),
        (b"newmtl a\nd 0.5\nTr 0.5\n", "duplicate"),
        (
            b"newmtl a\nmap_Kd -o 1 1 1 image.png\n",
            "only the texture option",
        ),
        (
            b"newmtl a\nmap_Kd a.png\nmap_Kd b.png\n",
            "duplicate texture",
        ),
        (b"newmtl a\nmap_Kd -clamp maybe a.png\n", "on or off"),
        (b"newmtl a\nmap_Kd\n", "path is missing"),
        (b"newmtl \xff\n", "UTF-8"),
    ],
)
def test_mtl_malformed_or_lossy_constructs_reject(mtl, message):
    obj = b"mtllib materials.mtl\n"
    with pytest.raises(ValueError, match=message):
        _core.read_obj(obj, mtl)


def _rebuild_mesh(mesh, **changes):
    kwargs = {}
    for name in (
        "vertex_normals",
        "corner_normals",
        "vertex_uvs",
        "corner_uvs",
        "vertex_colors",
        "corner_colors",
    ):
        value = np.asarray(getattr(mesh, name))
        if value.size:
            kwargs[name] = value
    if mesh.has_face_smoothing_groups:
        kwargs["face_smoothing_groups"] = np.asarray(
            mesh.face_smoothing_groups
        )
    if mesh.has_primitive_object_names:
        kwargs["primitive_object_names"] = mesh.primitive_object_names
    if mesh.has_primitive_group_names:
        kwargs["primitive_group_names"] = mesh.primitive_group_names
    if mesh.has_materials:
        kwargs["materials"] = mesh.materials
    kwargs.update(
        primitive_offsets=np.asarray(mesh.primitive_offsets),
        primitive_materials=np.asarray(mesh.primitive_materials),
        coordinate_frame=mesh.coordinate_frame,
        scale_to_meters=mesh.scale_to_meters,
        local_transform=np.asarray(mesh.local_transform),
    )
    kwargs.update(changes)
    return _core.mesh(
        np.asarray(mesh.positions),
        np.asarray(mesh.face_offsets),
        np.asarray(mesh.face_indices),
        **kwargs,
    )


def test_obj_writer_guard_does_not_silently_drop_conventions():
    mesh = _mesh()
    with pytest.raises(ValueError, match="require an MTL"):
        _core.write_obj(mesh)
    without_materials = _core.mesh(
        np.asarray(mesh.positions),
        np.asarray(mesh.face_offsets),
        np.asarray(mesh.face_indices),
    )
    with pytest.raises(ValueError, match="without materials"):
        _core.write_obj(without_materials, "materials.mtl")

    for names, message in [
        (["", "glass"], "non-empty"),
        (["same", "same"], "unique"),
    ]:
        invalid = _rebuild_mesh(
            mesh, materials=_core.material_set(names)
        )
        with pytest.raises(ValueError, match=message):
            _core.write_mtl(invalid.materials)

    cases = [
        ({"coordinate_frame": "opencv"}, "coordinate frame"),
        ({"scale_to_meters": 0.01}, "coordinate frame"),
        (
            {"vertex_normals": np.ones((5, 3), np.float32)},
            "simultaneous vertex and corner normals",
        ),
        (
            {"vertex_uvs": np.ones((5, 2), np.float32)},
            "simultaneous vertex and corner UV",
        ),
        (
            {"corner_colors": np.ones((7, 4), np.uint8)},
            "corner colors",
        ),
    ]
    for changes, message in cases:
        invalid = _rebuild_mesh(mesh, **changes)
        with pytest.raises(ValueError, match=message):
            _core.write_obj(invalid, "materials.mtl")

    colors = np.asarray(mesh.vertex_colors).copy()
    colors[0, 3] = 1
    invalid = _rebuild_mesh(mesh, vertex_colors=colors)
    with pytest.raises(ValueError, match="vertex alpha"):
        _core.write_obj(invalid, "materials.mtl")

    detached = _rebuild_mesh(
        without_materials,
        primitive_materials=np.array([3], np.int32),
    )
    with pytest.raises(ValueError, match="detached"):
        _core.write_obj(detached)


def test_writer_rejects_material_reset_and_unassociated_attribute_pools():
    base = _mesh()
    reset = _rebuild_mesh(
        base,
        primitive_materials=np.array([0, -1], np.int32),
    )
    with pytest.raises(ValueError, match="cannot follow"):
        _core.write_obj(reset, "materials.mtl")

    empty_faces = _core.mesh(
        np.array([[0, 0, 0]], np.float32),
        np.array([0], np.uint64),
        np.empty(0, np.uint64),
        vertex_normals=np.array([[0, 0, 1]], np.float32),
    )
    with pytest.raises(ValueError, match="without faces"):
        _core.write_obj(empty_faces)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"alpha_modes": ["mask"]}, "mask alpha"),
        (
            {
                "base_colors": np.array([[1, 1, 1, 0.5]], np.float32),
                "alpha_modes": ["opaque"],
            },
            "cannot round-trip",
        ),
        (
            {
                "alpha_cutoffs": np.array([0.25], np.float32),
            },
            "alpha cutoff",
        ),
        (
            {
                "texture_uv_sets": np.array([1], np.uint32),
            },
            "UV set zero",
        ),
        (
            {
                "texture_wrap_s": ["repeat"],
                "texture_wrap_t": ["clamp"],
            },
            "sampler wrap",
        ),
        (
            {
                "texture_min_filters": ["nearest"],
            },
            "sampler filters",
        ),
        (
            {
                "texture_semantics": ["occlusion"],
            },
            "semantic is not representable",
        ),
        (
            {
                "texture_paths": ["-option-like.png"],
            },
            "beginning with '-'",
        ),
    ],
)
def test_mtl_writer_guards_unrepresentable_material_features(kwargs, message):
    defaults = {
        "base_colors": np.ones((1, 4), np.float32),
        "alpha_modes": ["opaque"],
        "texture_materials": np.array([0], np.uint64),
        "texture_semantics": ["base_color"],
        "texture_paths": ["a.png"],
        "texture_uv_sets": np.array([0], np.uint32),
        "texture_wrap_s": ["repeat"],
        "texture_wrap_t": ["repeat"],
        "texture_min_filters": ["unspecified"],
    }
    defaults.update(kwargs)
    materials = _core.material_set(["a"], **defaults)
    with pytest.raises(ValueError, match=message):
        _core.write_mtl(materials)


def test_mtl_writer_preserves_texture_row_order_and_rejects_interleaving():
    ordered = _core.material_set(
        ["a", "b"],
        texture_materials=np.array([0, 0, 1], np.uint64),
        texture_semantics=["roughness", "base_color", "normal"],
        texture_paths=["rough.png", "base.png", "normal.png"],
    )
    decoded = _core.read_obj(
        b"mtllib materials.mtl\n", _core.write_mtl(ordered)
    )
    assert decoded.materials.texture_semantics == [
        "roughness",
        "base_color",
        "normal",
    ]
    assert decoded.materials.texture_paths == [
        "rough.png",
        "base.png",
        "normal.png",
    ]

    interleaved = _core.material_set(
        ["a", "b"],
        texture_materials=np.array([1, 0], np.uint64),
        texture_semantics=["normal", "base_color"],
        texture_paths=["normal.png", "base.png"],
    )
    with pytest.raises(ValueError, match="grouped by material"):
        _core.write_mtl(interleaved)


def test_writer_rejects_escaped_text_that_would_exceed_reader_line_limit():
    materials = _core.material_set(["#" * 600_000])
    with pytest.raises(ValueError, match="too long after"):
        _core.write_mtl(materials)


def test_empty_and_bom_inputs_are_defined():
    empty = _core.read_obj(b"")
    assert empty.num_vertices == empty.num_faces == 0
    bom = _core.read_obj(
        b"\xef\xbb\xbfv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"
    )
    assert bom.face_offsets.tolist() == [0, 3]


@pytest.mark.parametrize("corner_domain", [False, True])
def test_randomized_valid_meshes_roundtrip_bit_exact(corner_domain):
    rng = np.random.default_rng(20260725 + corner_domain)
    for case in range(20):
        vertices = int(rng.integers(4, 20))
        faces = int(rng.integers(1, 9))
        corner_counts = rng.integers(3, min(vertices, 7), size=faces)
        offsets = np.concatenate(
            ([0], np.cumsum(corner_counts, dtype=np.uint64))
        ).astype(np.uint64)
        indices = np.concatenate(
            [
                rng.choice(vertices, size=int(count), replace=False)
                for count in corner_counts
            ]
        ).astype(np.uint64)
        corners = len(indices)
        kwargs = {
            "vertex_colors": rng.integers(
                0, 256, size=(vertices, 4), dtype=np.uint8
            ),
            "primitive_offsets": np.arange(faces + 1, dtype=np.uint64),
            "primitive_materials": np.full(faces, -1, np.int32),
            "face_smoothing_groups": rng.integers(
                0, 10, size=faces, dtype=np.uint32
            ),
            "primitive_object_names": [
                f"object {case} #{face}" for face in range(faces)
            ],
            "primitive_group_names": [
                f"group {face}" for face in range(faces)
            ],
        }
        kwargs["vertex_colors"][:, 3] = 255
        if corner_domain:
            kwargs["corner_normals"] = rng.standard_normal(
                (corners, 3), dtype=np.float32
            )
            kwargs["corner_uvs"] = rng.standard_normal(
                (corners, 2), dtype=np.float32
            )
        else:
            kwargs["vertex_normals"] = rng.standard_normal(
                (vertices, 3), dtype=np.float32
            )
            kwargs["vertex_uvs"] = rng.standard_normal(
                (vertices, 2), dtype=np.float32
            )
        expected = _core.mesh(
            rng.standard_normal((vertices, 3), dtype=np.float32),
            offsets,
            indices,
            **kwargs,
        )
        actual = _core.read_obj(_core.write_obj(expected))
        _assert_mesh_equal(actual, expected)


def _decode_outcome(data):
    try:
        mesh = _core.read_obj(data)
    except Exception as exc:
        return ("error", type(exc).__name__, str(exc))
    return (
        "ok",
        bytes(np.asarray(mesh.positions)),
        bytes(np.asarray(mesh.face_offsets)),
        bytes(np.asarray(mesh.face_indices)),
    )


def test_scheduled_random_mutations_match_bytes_and_mmap(tmp_path):
    seed = (
        b"v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        b"vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n"
        b"vn 0 0 1\nf 1/1/1 2/2/1 3/3/1 4/4/1\n"
    )
    cases = int(os.environ.get("SCENEIO_MMAP_FUZZ_CASES", "3"))
    rng = np.random.default_rng(20260725)
    for case in range(cases):
        mutated = bytearray(seed)
        operation = case % 3
        if operation == 0:
            mutated[int(rng.integers(0, len(mutated)))] ^= int(
                rng.integers(1, 256)
            )
        elif operation == 1:
            del mutated[int(rng.integers(1, len(mutated))) :]
        else:
            mutated.extend(rng.integers(0, 256, 7, dtype=np.uint8).tobytes())
        data = bytes(mutated)
        expected = _decode_outcome(data)
        path = tmp_path / f"mutation-{case}.obj"
        path.write_bytes(data)
        with (
            path.open("rb") as stream,
            mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
        ):
            actual = _decode_outcome(mapped)
        assert actual == expected
