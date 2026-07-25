"""Independent parity and malformed-input suite for polygon-preserving mesh PLY."""

from __future__ import annotations

import gc
import mmap
import struct
import tracemalloc

import numpy as np
import pytest

import sceneio
from sceneio import _core


def _ascii_fixture() -> bytes:
    header = """ply
format ascii 1.0
comment independent fixture
comment sceneio_coordinate_frame opengl
comment sceneio_scale_to_meters 0.01
comment sceneio_local_transform 1 0 0 2 0 1 0 3 0 0 1 4 0 0 0 1
element vertex 5
property double x
property double y
property double z
property float nx
property float ny
property float nz
property float texture_u
property float texture_v
property uchar red
property uchar green
property uchar blue
property uchar alpha
element face 2
property list uchar uint vertex_indices
property list uchar float texcoord
property list uchar float corner_normals
property list uchar uchar corner_colors
property int material_index
property uint primitive_index
end_header
"""
    vertices = [
        "0 0 0 0 0 1 0 0 10 20 30 40",
        "1 0 0 0 0 1 1 0 50 60 70 80",
        "1 1 0 0 0 1 1 1 90 100 110 120",
        "0 1 0 0 0 1 0 1 130 140 150 160",
        "0 0 1 0 1 0 .5 .5 170 180 190 200",
    ]
    face0 = (
        "4 0 1 2 3 "
        "8 0 0 1 0 1 1 0 1 "
        "12 0 0 1 0 0 1 0 0 1 0 0 1 "
        "16 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 "
        "2 0"
    )
    face1 = (
        "3 0 3 4 "
        "6 0 0 0 1 .5 .5 "
        "9 1 0 0 1 0 0 1 0 0 "
        "12 21 22 23 24 25 26 27 28 29 30 31 32 "
        "-1 1"
    )
    return (header + "\n".join([*vertices, face0, face1]) + "\n").encode()


def _binary_be_fixture() -> bytes:
    header = b"""ply
format binary_big_endian 1.0
comment sceneio_coordinate_frame enu
element vertex 5
property double x
property double y
property double z
property uchar red
property uchar green
property uchar blue
element face 2
property list uchar ushort vertex_index
property short material_index
end_header
"""
    vertices = [
        (0.0, 0.0, 0.0, 1, 2, 3),
        (1.0, 0.0, 0.0, 4, 5, 6),
        (1.0, 1.0, 0.0, 7, 8, 9),
        (0.0, 1.0, 0.0, 10, 11, 12),
        (0.0, 0.0, 1.0, 13, 14, 15),
    ]
    body = bytearray()
    for row in vertices:
        body += struct.pack(">dddBBB", *row)
    body += struct.pack(">B4Hh", 4, 0, 1, 2, 3, 7)
    body += struct.pack(">B3Hh", 3, 0, 3, 4, -1)
    return header + body


def _full_mesh():
    return _core.mesh(
        np.array(
            [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1]],
            np.float32,
        ),
        np.array([0, 4, 7], np.uint64),
        np.array([0, 1, 2, 3, 0, 3, 4], np.uint64),
        vertex_normals=np.arange(15, dtype=np.float32).reshape(5, 3) / 20,
        corner_normals=np.arange(21, dtype=np.float32).reshape(7, 3) / 30,
        vertex_uvs=np.arange(10, dtype=np.float32).reshape(5, 2) / 10,
        corner_uvs=np.arange(14, dtype=np.float32).reshape(7, 2) / 14,
        vertex_colors=np.arange(20, dtype=np.uint8).reshape(5, 4),
        corner_colors=np.arange(28, dtype=np.uint8).reshape(7, 4),
        primitive_offsets=np.array([0, 1, 2], np.uint64),
        primitive_materials=np.array([3, -1], np.int32),
        coordinate_frame="opencv",
        scale_to_meters=0.001,
        local_transform=np.array(
            [[1, 0, 0, 2], [0, 1, 0, 3], [0, 0, 1, 4], [0, 0, 0, 1]],
            np.float64,
        ),
    )


def _assert_equal(left, right):
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
        "local_transform",
    ):
        np.testing.assert_array_equal(getattr(left, name), getattr(right, name))
    assert left.coordinate_frame == right.coordinate_frame
    assert left.scale_to_meters == right.scale_to_meters


def _slice_faces(mesh, start, stop):
    """Construct the expected canonical face slice without using the decoder."""

    corner_start = int(mesh.face_offsets[start])
    corner_stop = int(mesh.face_offsets[stop])
    kwargs = {}
    for name in ("vertex_normals", "vertex_uvs", "vertex_colors"):
        if getattr(mesh, f"has_{name}"):
            kwargs[name] = np.asarray(getattr(mesh, name))
    for name in ("corner_normals", "corner_uvs", "corner_colors"):
        if getattr(mesh, f"has_{name}"):
            kwargs[name] = np.asarray(getattr(mesh, name))[corner_start:corner_stop]

    primitive_offsets = [0]
    primitive_materials = []
    for primitive, material in enumerate(mesh.primitive_materials):
        primitive_start = int(mesh.primitive_offsets[primitive])
        primitive_stop = int(mesh.primitive_offsets[primitive + 1])
        clipped_start = max(start, primitive_start)
        clipped_stop = min(stop, primitive_stop)
        if clipped_start < clipped_stop:
            primitive_offsets.append(clipped_stop - start)
            primitive_materials.append(int(material))

    return _core.mesh(
        np.asarray(mesh.positions),
        np.asarray(mesh.face_offsets[start : stop + 1])
        - np.uint64(corner_start),
        np.asarray(mesh.face_indices)[corner_start:corner_stop],
        primitive_offsets=np.asarray(primitive_offsets, np.uint64),
        primitive_materials=np.asarray(primitive_materials, np.int32),
        coordinate_frame=mesh.coordinate_frame,
        scale_to_meters=mesh.scale_to_meters,
        local_transform=np.asarray(mesh.local_transform),
        **kwargs,
    )


def _oracle_decode_sceneio_writer(data: bytes) -> dict[str, np.ndarray]:
    """Parse the deterministic writer independently with struct/NumPy only."""

    marker = b"end_header\n"
    body_offset = data.index(marker) + len(marker)
    header = data[:body_offset].decode("ascii").splitlines()
    assert header[:2] == ["ply", "format binary_little_endian 1.0"]
    vertex_line = next(line for line in header if line.startswith("element vertex "))
    face_line = next(line for line in header if line.startswith("element face "))
    vertex_count = int(vertex_line.rsplit(" ", 1)[1])
    face_count = int(face_line.rsplit(" ", 1)[1])
    vertex_start = header.index(vertex_line)
    face_start = header.index(face_line)
    vertex_properties = header[vertex_start + 1 : face_start]
    face_properties = header[face_start + 1 : header.index("end_header")]
    expected_vertex = [
        "property float x",
        "property float y",
        "property float z",
    ]
    flags = {
        "vertex_normals": "property float nx" in vertex_properties,
        "vertex_uvs": "property float texture_u" in vertex_properties,
        "vertex_colors": "property uchar red" in vertex_properties,
        "corner_uvs": "property list uint float texcoord" in face_properties,
        "corner_normals": (
            "property list uint float corner_normals" in face_properties
        ),
        "corner_colors": (
            "property list uint uchar corner_colors" in face_properties
        ),
    }
    assert vertex_properties[:3] == expected_vertex

    cursor = body_offset

    def take(fmt):
        nonlocal cursor
        size = struct.calcsize(fmt)
        result = struct.unpack_from(fmt, data, cursor)
        cursor += size
        return result

    positions = np.empty((vertex_count, 3), np.float32)
    vertex_normals = np.empty((vertex_count, 3), np.float32)
    vertex_uvs = np.empty((vertex_count, 2), np.float32)
    vertex_colors = np.empty((vertex_count, 4), np.uint8)
    for row in range(vertex_count):
        positions[row] = take("<3f")
        if flags["vertex_normals"]:
            vertex_normals[row] = take("<3f")
        if flags["vertex_uvs"]:
            vertex_uvs[row] = take("<2f")
        if flags["vertex_colors"]:
            vertex_colors[row] = take("<4B")

    offsets = [0]
    indices = []
    corner_uvs = []
    corner_normals = []
    corner_colors = []
    materials = []
    primitives = []
    for _ in range(face_count):
        count = take("<I")[0]
        indices.extend(take(f"<{count}I"))
        if flags["corner_uvs"]:
            assert take("<I")[0] == count * 2
            corner_uvs.extend(take(f"<{count * 2}f"))
        if flags["corner_normals"]:
            assert take("<I")[0] == count * 3
            corner_normals.extend(take(f"<{count * 3}f"))
        if flags["corner_colors"]:
            assert take("<I")[0] == count * 4
            corner_colors.extend(take(f"<{count * 4}B"))
        materials.append(take("<i")[0])
        primitives.append(take("<I")[0])
        offsets.append(len(indices))
    assert cursor == len(data)
    return {
        "positions": positions,
        "face_offsets": np.asarray(offsets, np.uint64),
        "face_indices": np.asarray(indices, np.uint64),
        "vertex_normals": (
            vertex_normals if flags["vertex_normals"] else np.empty((0, 3))
        ),
        "vertex_uvs": vertex_uvs if flags["vertex_uvs"] else np.empty((0, 2)),
        "vertex_colors": (
            vertex_colors if flags["vertex_colors"] else np.empty((0, 4))
        ),
        "corner_normals": np.asarray(corner_normals, np.float32).reshape(-1, 3),
        "corner_uvs": np.asarray(corner_uvs, np.float32).reshape(-1, 2),
        "corner_colors": np.asarray(corner_colors, np.uint8).reshape(-1, 4),
        "materials": np.asarray(materials, np.int32),
        "primitives": np.asarray(primitives, np.uint32),
    }


def _oracle_encode_ascii(mesh) -> bytes:
    """Independent canonical-to-PLY writer used to test the native reader."""

    header = [
        "ply",
        "format ascii 1.0",
        f"comment sceneio_coordinate_frame {mesh.coordinate_frame}",
        f"comment sceneio_scale_to_meters {mesh.scale_to_meters:.17g}",
        "comment sceneio_local_transform "
        + " ".join(
            f"{float(value):.17g}"
            for value in np.asarray(mesh.local_transform).reshape(-1)
        ),
        f"element vertex {mesh.num_vertices}",
        "property float x",
        "property float y",
        "property float z",
    ]
    if mesh.has_vertex_normals:
        header += [
            "property float nx",
            "property float ny",
            "property float nz",
        ]
    if mesh.has_vertex_uvs:
        header += ["property float texture_u", "property float texture_v"]
    if mesh.has_vertex_colors:
        header += [
            "property uchar red",
            "property uchar green",
            "property uchar blue",
            "property uchar alpha",
        ]
    header += [
        f"element face {mesh.num_faces}",
        "property list uint uint vertex_indices",
    ]
    if mesh.has_corner_uvs:
        header.append("property list uint float texcoord")
    if mesh.has_corner_normals:
        header.append("property list uint float corner_normals")
    if mesh.has_corner_colors:
        header.append("property list uint uchar corner_colors")
    header += [
        "property int material_index",
        "property uint primitive_index",
        "end_header",
    ]
    rows = []
    for vertex in range(mesh.num_vertices):
        values = [*mesh.positions[vertex]]
        if mesh.has_vertex_normals:
            values += [*mesh.vertex_normals[vertex]]
        if mesh.has_vertex_uvs:
            values += [*mesh.vertex_uvs[vertex]]
        text = [f"{float(value):.9g}" for value in values]
        if mesh.has_vertex_colors:
            text += [str(int(value)) for value in mesh.vertex_colors[vertex]]
        rows.append(" ".join(text))

    primitive = 0
    for face in range(mesh.num_faces):
        while face >= mesh.primitive_offsets[primitive + 1]:
            primitive += 1
        begin = int(mesh.face_offsets[face])
        end = int(mesh.face_offsets[face + 1])
        corners = end - begin
        text = [
            str(corners),
            *(str(int(value)) for value in mesh.face_indices[begin:end]),
        ]
        if mesh.has_corner_uvs:
            values = mesh.corner_uvs[begin:end].reshape(-1)
            text += [str(len(values)), *(f"{float(value):.9g}" for value in values)]
        if mesh.has_corner_normals:
            values = mesh.corner_normals[begin:end].reshape(-1)
            text += [str(len(values)), *(f"{float(value):.9g}" for value in values)]
        if mesh.has_corner_colors:
            values = mesh.corner_colors[begin:end].reshape(-1)
            text += [str(len(values)), *(str(int(value)) for value in values)]
        text += [
            str(int(mesh.primitive_materials[primitive])),
            str(primitive),
        ]
        rows.append(" ".join(text))
    return ("\n".join([*header, *rows]) + "\n").encode()


def test_ascii_independent_fixture_preserves_every_domain():
    mesh = _core.read_ply_mesh(_ascii_fixture())
    assert mesh.num_vertices == 5
    assert mesh.face_offsets.tolist() == [0, 4, 7]
    assert mesh.face_indices.tolist() == [0, 1, 2, 3, 0, 3, 4]
    np.testing.assert_array_equal(mesh.positions[-1], [0, 0, 1])
    np.testing.assert_array_equal(mesh.vertex_normals[-1], [0, 1, 0])
    np.testing.assert_array_equal(mesh.vertex_uvs[-1], [0.5, 0.5])
    np.testing.assert_array_equal(mesh.vertex_colors[-1], [170, 180, 190, 200])
    np.testing.assert_array_equal(
        mesh.corner_uvs[:4], [[0, 0], [1, 0], [1, 1], [0, 1]]
    )
    np.testing.assert_array_equal(mesh.corner_normals[:4], [[0, 0, 1]] * 4)
    np.testing.assert_array_equal(mesh.corner_colors[0], [1, 2, 3, 4])
    assert mesh.primitive_offsets.tolist() == [0, 1, 2]
    assert mesh.primitive_materials.tolist() == [2, -1]
    assert mesh.coordinate_frame == "opengl"
    assert mesh.scale_to_meters == 0.01
    np.testing.assert_array_equal(
        mesh.local_transform,
        [[1, 0, 0, 2], [0, 1, 0, 3], [0, 0, 1, 4], [0, 0, 0, 1]],
    )


def test_binary_big_endian_aliases_and_rgb_alpha_default():
    mesh = _core.read_ply_mesh(_binary_be_fixture())
    assert mesh.face_offsets.tolist() == [0, 4, 7]
    assert mesh.face_indices.tolist() == [0, 1, 2, 3, 0, 3, 4]
    np.testing.assert_array_equal(mesh.positions[-1], [0, 0, 1])
    np.testing.assert_array_equal(mesh.vertex_colors[0], [1, 2, 3, 255])
    np.testing.assert_array_equal(mesh.vertex_colors[-1], [13, 14, 15, 255])
    assert mesh.primitive_offsets.tolist() == [0, 1, 2]
    assert mesh.primitive_materials.tolist() == [7, -1]
    assert mesh.coordinate_frame == "enu"


@pytest.mark.parametrize(
    "source",
    [
        pytest.param(lambda: bytes(_core.write_ply_mesh(_full_mesh())), id="writer"),
        pytest.param(_ascii_fixture, id="independent-ascii"),
        pytest.param(_binary_be_fixture, id="independent-big-endian"),
    ],
)
@pytest.mark.parametrize(("start", "stop"), [(0, 1), (1, 2), (0, 2)])
def test_native_face_range_is_bit_exact_slice(source, start, stop):
    data = source()
    full = _core.read_ply_mesh(data)
    partial = _core.read_ply_mesh_faces(data, start, stop)
    _assert_equal(_slice_faces(full, start, stop), partial)


def test_native_face_range_rejects_invalid_ranges_and_impossible_counts():
    data = _ascii_fixture()
    for start, stop in ((0, 0), (1, 1), (2, 1), (0, 3)):
        with pytest.raises(ValueError, match=r"range|extent"):
            _core.read_ply_mesh_faces(data, start, stop)

    malformed = b"""ply
format binary_little_endian 1.0
element vertex 1000000000
property float x
property float y
property float z
element face 1000000000
property list uchar uint vertex_indices
end_header
"""
    with pytest.raises(ValueError, match=r"declared .* counts exceed payload"):
        _core.read_ply_mesh_faces(malformed, 0, 1)


def test_face_list_count_rejects_before_unbounded_allocation():
    header = b"""ply
format binary_little_endian 1.0
element vertex 1
property float x
property float y
property float z
element face 1
property list uint uint vertex_indices
end_header
"""
    malformed = header + b"\0" * 12 + struct.pack("<I", 0xFFFFFFFF) + b"\0" * 12
    for reader in (
        _core.read_ply_mesh,
        lambda data: _core.read_ply_mesh_faces(data, 0, 1),
    ):
        with pytest.raises(ValueError, match="list count exceeds payload"):
            reader(malformed)


def test_native_face_range_validates_malformed_skipped_faces():
    malformed_before = _replace(
        _ascii_fixture(), b"4 0 1 2 3 ", b"4 0 1 2 9 "
    )
    with pytest.raises(ValueError, match="outside the vertex"):
        _core.read_ply_mesh_faces(malformed_before, 1, 2)

    malformed_after = _replace(_ascii_fixture(), b"-1 1\n", b"-1 3\n")
    with pytest.raises(ValueError, match="contiguous runs"):
        _core.read_ply_mesh_faces(malformed_after, 0, 1)


def test_writer_is_deterministic_roundtrips_and_matches_independent_oracle():
    mesh = _full_mesh()
    first = bytes(_core.write_ply_mesh(mesh))
    second = bytes(_core.write_ply_mesh(mesh))
    assert first == second
    decoded = _core.read_ply_mesh(first)
    _assert_equal(mesh, decoded)

    oracle = _oracle_decode_sceneio_writer(first)
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
    ):
        np.testing.assert_array_equal(oracle[name], getattr(mesh, name))
    np.testing.assert_array_equal(oracle["materials"], [3, -1])
    np.testing.assert_array_equal(oracle["primitives"], [0, 1])


@pytest.mark.parametrize("seed", range(20))
def test_randomized_writer_reader_and_oracle_parity(seed):
    rng = np.random.default_rng(seed)
    vertices = int(rng.integers(3, 40))
    faces = int(rng.integers(1, 25))
    sizes = rng.integers(3, min(vertices, 9) + 1, size=faces)
    offsets = np.concatenate([[0], np.cumsum(sizes)]).astype(np.uint64)
    indices = np.concatenate(
        [rng.choice(vertices, int(size), replace=False) for size in sizes]
    ).astype(np.uint64)
    corners = len(indices)
    primitive_breaks = [0]
    while primitive_breaks[-1] < faces:
        primitive_breaks.append(
            min(faces, primitive_breaks[-1] + int(rng.integers(1, 5)))
        )
    kwargs = {}
    for name, shape, dtype in (
        ("vertex_normals", (vertices, 3), np.float32),
        ("corner_normals", (corners, 3), np.float32),
        ("vertex_uvs", (vertices, 2), np.float32),
        ("corner_uvs", (corners, 2), np.float32),
        ("vertex_colors", (vertices, 4), np.uint8),
        ("corner_colors", (corners, 4), np.uint8),
    ):
        if rng.integers(2):
            kwargs[name] = (
                rng.integers(0, 256, size=shape, dtype=np.uint8)
                if dtype is np.uint8
                else rng.normal(size=shape).astype(np.float32)
            )
    mesh = _core.mesh(
        rng.normal(size=(vertices, 3)).astype(np.float32),
        offsets,
        indices,
        primitive_offsets=np.asarray(primitive_breaks, np.uint64),
        primitive_materials=rng.integers(
            -1, 6, size=len(primitive_breaks) - 1, dtype=np.int32
        ),
        **kwargs,
    )
    encoded = bytes(_core.write_ply_mesh(mesh))
    _assert_equal(mesh, _core.read_ply_mesh(encoded))
    oracle = _oracle_decode_sceneio_writer(encoded)
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
    ):
        np.testing.assert_array_equal(oracle[name], getattr(mesh, name))
    oracle_ascii = _oracle_encode_ascii(mesh)
    _assert_equal(mesh, _core.read_ply_mesh(oracle_ascii))
    start = int(rng.integers(0, faces))
    stop = int(rng.integers(start + 1, faces + 1))
    expected = _slice_faces(mesh, start, stop)
    _assert_equal(
        expected, _core.read_ply_mesh_faces(encoded, start, stop)
    )
    _assert_equal(
        expected, _core.read_ply_mesh_faces(oracle_ascii, start, stop)
    )


def test_readonly_memoryview_mmap_lifetime_and_mutation_isolation(tmp_path):
    expected = _core.read_ply_mesh(_ascii_fixture())
    backing = bytearray(_ascii_fixture())
    readonly = memoryview(backing).toreadonly()
    decoded = _core.read_ply_mesh(readonly)
    backing[:] = b"\0" * len(backing)
    del readonly
    gc.collect()
    _assert_equal(expected, decoded)

    path = tmp_path / "mesh.ply"
    path.write_bytes(bytes(_core.write_ply_mesh(_full_mesh())))
    with path.open("rb") as stream:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        from_map = _core.read_ply_mesh(mapped)
        mapped.close()
    gc.collect()
    _assert_equal(_full_mesh(), from_map)


def test_public_detect_read_write_inspect_and_direct_sink(tmp_path):
    path = tmp_path / "mesh.ply"
    mesh = _full_mesh()
    sceneio.write(mesh, path)
    assert sceneio.detect(path) == "ply_mesh"
    decoded = sceneio.read(path)
    _assert_equal(mesh, decoded)
    info = sceneio.inspect(path)
    assert info.format == "ply_mesh"
    assert info.datatype == "mesh"
    assert info.shape == (5, 3)
    assert info.count == 5
    assert info.metadata["num_faces"] == 2
    assert info.metadata["has_corner_uvs"]
    assert info.metadata["coordinate_frame"] == "opencv"
    assert info.metadata["scale_to_meters"] == 0.001
    assert info.metadata["local_transform"] == tuple(
        mesh.local_transform.reshape(-1)
    )
    assert sceneio.capabilities("ply_mesh").streams_read
    assert sceneio.capabilities("ply_mesh").streams_write
    assert sceneio.capabilities("ply_mesh").partial_selectors == ("faces",)

    partial = sceneio.read_partial(path, faces=(1, 2))
    _assert_equal(_slice_faces(mesh, 1, 2), partial)


def test_sceneio_triangle_output_opens_in_trimesh(tmp_path):
    trimesh = pytest.importorskip("trimesh")
    mesh = _core.mesh(
        np.array(
            [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
            np.float32,
        ),
        np.array([0, 3, 6], np.uint64),
        np.array([0, 1, 2, 0, 2, 3], np.uint64),
    )
    path = tmp_path / "triangles.ply"
    sceneio.write(mesh, path)
    external = trimesh.load(
        path, process=False, maintain_order=True, force="mesh"
    )
    np.testing.assert_array_equal(external.vertices, mesh.positions)
    np.testing.assert_array_equal(
        external.faces, [[0, 1, 2], [0, 2, 3]]
    )


def _replace(data: bytes, old: bytes, new: bytes) -> bytes:
    assert data.count(old) == 1
    return data.replace(old, new)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda data: _replace(
                data, b"element face 2", b"element edge 2"
            ),
            "elements must be",
        ),
        (
            lambda data: _replace(
                data,
                b"property double x",
                b"property list uchar double x",
            ),
            "list-valued vertex",
        ),
        (
            lambda data: _replace(
                data, b"property double x", b"property double mystery"
            ),
            "unsupported vertex property",
        ),
        (
            lambda data: _replace(
                data,
                b"property list uchar uint vertex_indices",
                b"property float vertex_indices",
            ),
            "vertex indices",
        ),
        (
            lambda data: _replace(
                data,
                b"property list uchar float texcoord",
                b"property list float float texcoord",
            ),
            "list count type",
        ),
        (
            lambda data: _replace(
                data,
                b"property int material_index",
                b"property float material_index",
            ),
            "material_index",
        ),
        (
            lambda data: _replace(
                data,
                b"comment sceneio_coordinate_frame opengl",
                b"comment sceneio_unknown opengl",
            ),
            "unsupported SceneIO",
        ),
        (
            lambda data: _replace(
                data,
                b"comment independent fixture",
                b"comment TextureFile texture.png",
            ),
            "require MaterialSet",
        ),
        (
            lambda data: _replace(
                data,
                b"comment independent fixture",
                b"obj_info source object",
            ),
            "obj_info metadata",
        ),
    ],
)
def test_schema_and_metadata_rejections(mutate, message):
    with pytest.raises(ValueError, match=message):
        _core.read_ply_mesh(mutate(_ascii_fixture()))


def test_face_list_lengths_indices_and_primitive_runs_reject():
    data = _ascii_fixture()
    cases = [
        (_replace(data, b"4 0 1 2 3 ", b"2 0 1 "), "at least three"),
        (_replace(data, b"4 0 1 2 3 ", b"4 0 1 2 9 "), "outside the vertex"),
        (
            _replace(data, b"8 0 0 1 0 1 1 0 1 ", b"6 0 0 1 0 1 1 "),
            "texcoord list length",
        ),
        (_replace(data, b"-1 1\n", b"-1 3\n"), "contiguous runs"),
        (_replace(data, b"-1 1\n", b"-2 1\n"), "material index"),
        (_replace(data, b"-1 1\n", b"3 0\n"), "material changes"),
    ]
    for malformed, message in cases:
        with pytest.raises(ValueError, match=message):
            _core.read_ply_mesh(malformed)


def test_truncated_trailing_and_mutable_input_reject():
    encoded = bytes(_core.write_ply_mesh(_full_mesh()))
    for malformed in (encoded[:20], encoded[:-1], encoded + b"x"):
        with pytest.raises(ValueError):
            _core.read_ply_mesh(malformed)
    with pytest.raises(ValueError, match="read-only"):
        _core.read_ply_mesh(bytearray(encoded))


@pytest.mark.parametrize(
    "encoding",
    ["ascii", "binary_little_endian", "binary_big_endian"],
)
def test_impossible_declared_counts_reject_before_record_allocation(encoding):
    malformed = f"""ply
format {encoding} 1.0
element vertex 1000000000
property float x
property float y
property float z
element face 1000000000
property list uchar uint vertex_indices
end_header
""".encode()
    with pytest.raises(ValueError, match=r"declared .* counts exceed payload"):
        _core.read_ply_mesh(malformed)


def test_writer_revalidates_mutable_views_and_does_not_truncate_target(tmp_path):
    mesh = _full_mesh()
    mesh.face_indices[0] = mesh.num_vertices
    with pytest.raises(ValueError, match="outside the vertex"):
        _core.write_ply_mesh(mesh)

    path = tmp_path / "preserve.ply"
    path.write_bytes(b"preserve")
    with pytest.raises(sceneio.FormatError, match="outside the vertex"):
        sceneio.write(mesh, path, format="ply_mesh")
    assert path.read_bytes() == b"preserve"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"face_smoothing_groups": np.array([1, 1], np.uint32)},
        {"primitive_object_names": ["first", "second"]},
        {"primitive_group_names": ["first", "second"]},
        {"materials": "make_material_set"},
    ],
)
def test_writer_rejects_obj_only_metadata(kwargs):
    mesh = _full_mesh()
    if kwargs.get("materials") == "make_material_set":
        kwargs = {"materials": _core.material_set(["a", "b", "c", "d"])}
    rebuilt = _core.mesh(
        np.asarray(mesh.positions),
        np.asarray(mesh.face_offsets),
        np.asarray(mesh.face_indices),
        vertex_normals=np.asarray(mesh.vertex_normals),
        corner_normals=np.asarray(mesh.corner_normals),
        vertex_uvs=np.asarray(mesh.vertex_uvs),
        corner_uvs=np.asarray(mesh.corner_uvs),
        vertex_colors=np.asarray(mesh.vertex_colors),
        corner_colors=np.asarray(mesh.corner_colors),
        primitive_offsets=np.asarray(mesh.primitive_offsets),
        primitive_materials=np.asarray(mesh.primitive_materials),
        coordinate_frame=mesh.coordinate_frame,
        scale_to_meters=mesh.scale_to_meters,
        local_transform=np.asarray(mesh.local_transform),
        **kwargs,
    )
    with pytest.raises(ValueError, match="not representable"):
        _core.write_ply_mesh(rebuilt)


def test_empty_mesh_roundtrip():
    mesh = _core.mesh(
        np.empty((0, 3), np.float32),
        np.array([0], np.uint64),
        np.empty(0, np.uint64),
    )
    _assert_equal(mesh, _core.read_ply_mesh(_core.write_ply_mesh(mesh)))


def test_generated_100mb_mesh_mmap_avoids_whole_file_python_copy(tmp_path):
    vertices = 4_400_000
    header = f"""ply
format binary_little_endian 1.0
element vertex {vertices}
property float x
property float y
property float z
property float nx
property float ny
property float nz
element face 0
property list uchar uint vertex_indices
end_header
""".encode()
    path = tmp_path / "large-mesh.ply"
    with path.open("wb") as stream:
        stream.write(header)
        stream.truncate(len(header) + vertices * 24)
    assert path.stat().st_size > 100 * 1024 * 1024

    tracemalloc.start()
    try:
        mesh = sceneio.read(path, format="ply_mesh")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert mesh.num_vertices == vertices
    assert mesh.num_faces == 0
    assert peak < 4 * 1024 * 1024
