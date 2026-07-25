"""Independent parity, guard, mmap, partial, and sink tests for STL."""

from __future__ import annotations

import gc
import io
import locale
import mmap
import struct

import numpy as np
import pytest
import trimesh
from trimesh.exchange import stl as trimesh_stl

import sceneio
from sceneio import _core


def _triangle_soup(*, normals: bool = True):
    positions = np.array(
        [
            [0, 0, 0],
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
            [1, 0, 1],
            [0, 1, 1],
        ],
        np.float32,
    )
    kwargs = {}
    if normals:
        kwargs["corner_normals"] = np.array(
            [[0, 0, 1]] * 3 + [[0, 0, -1]] * 3,
            np.float32,
        )
    return _core.mesh(
        positions,
        np.array([0, 3, 6], np.uint64),
        np.arange(6, dtype=np.uint64),
        **kwargs,
    )


def _manual_binary(
    triangles: np.ndarray,
    normals: np.ndarray,
    *,
    header: bytes = b"independent fixture",
    attributes: tuple[int, ...] | None = None,
) -> bytes:
    prefix = header[:80].ljust(80, b"\0")
    records = []
    if attributes is None:
        attributes = (0,) * len(triangles)
    for normal, triangle, attribute in zip(
        normals, triangles, attributes, strict=True
    ):
        records.append(
            struct.pack(
                "<12fH",
                *normal.tolist(),
                *triangle.reshape(-1).tolist(),
                attribute,
            )
        )
    return prefix + struct.pack("<I", len(records)) + b"".join(records)


def _manual_parse_binary(data: bytes):
    count = struct.unpack_from("<I", data, 80)[0]
    assert len(data) == 84 + count * 50
    normals = np.empty((count, 3), np.float32)
    triangles = np.empty((count, 3, 3), np.float32)
    attributes = []
    for face in range(count):
        values = struct.unpack_from("<12fH", data, 84 + face * 50)
        normals[face] = values[:3]
        triangles[face] = np.asarray(values[3:12]).reshape(3, 3)
        attributes.append(values[12])
    return normals, triangles, attributes


def _assert_soup(mesh, triangles, normals=None):
    np.testing.assert_array_equal(
        mesh.positions, np.asarray(triangles, np.float32).reshape(-1, 3)
    )
    np.testing.assert_array_equal(
        mesh.face_offsets,
        np.arange(0, len(triangles) * 3 + 1, 3, dtype=np.uint64),
    )
    np.testing.assert_array_equal(
        mesh.face_indices, np.arange(len(triangles) * 3, dtype=np.uint64)
    )
    if normals is None or not np.any(normals):
        assert mesh.corner_normals.shape == (0, 3)
    else:
        np.testing.assert_array_equal(
            mesh.corner_normals, np.repeat(normals, 3, axis=0)
        )


def test_independent_binary_fixture_and_solid_header_detection():
    triangles = np.array(
        [[[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 0, 1], [1, 0, 1], [0, 1, 1]]],
        np.float32,
    )
    normals = np.array([[0, 0, 1], [0, 0, -1]], np.float32)
    data = _manual_binary(triangles, normals, header=b"solid binary trap")
    decoded = _core.read_stl(data)
    _assert_soup(decoded, triangles, normals)
    assert _core._inspect_stl(data) == {
        "encoding": "binary",
        "num_vertices": 6,
        "num_faces": 2,
        "num_corners": 6,
        "has_facet_normals": True,
    }


def test_independent_ascii_fixture_is_case_insensitive_and_strict():
    data = b"""SoLiD oracle
FaCeT NoRmAl 0 0 1
  OuTeR LoOp
    VeRtEx 0 0 0
    VeRtEx 1 0 0
    VeRtEx 0 1 0
  EnDlOoP
EnDfAcEt
EnDsOlId oracle
"""
    decoded = _core.read_stl(data)
    _assert_soup(
        decoded,
        np.array([[[0, 0, 0], [1, 0, 0], [0, 1, 0]]], np.float32),
        np.array([[0, 0, 1]], np.float32),
    )
    assert _core._inspect_stl(data)["encoding"] == "ascii"


@pytest.mark.parametrize("encoding", ["binary", "ascii"])
def test_writer_bytes_are_independently_parseable(encoding):
    mesh = _triangle_soup()
    data = bytes(_core.write_stl(mesh, encoding))
    if encoding == "binary":
        normals, triangles, attributes = _manual_parse_binary(data)
        np.testing.assert_array_equal(triangles.reshape(-1, 3), mesh.positions)
        np.testing.assert_array_equal(
            np.repeat(normals, 3, axis=0), mesh.corner_normals
        )
        assert attributes == [0, 0]
    else:
        oracle = trimesh.load_mesh(
            file_obj=io.BytesIO(data), file_type="stl", process=False
        )
        np.testing.assert_allclose(
            np.asarray(oracle.triangles),
            np.asarray(mesh.positions).reshape(-1, 3, 3),
        )


def test_trimesh_binary_and_ascii_writer_outputs_decode():
    oracle = trimesh.Trimesh(
        vertices=np.array(
            [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], np.float64
        ),
        faces=np.array([[0, 1, 2], [0, 3, 1]]),
        process=False,
    )
    for data in (
        trimesh_stl.export_stl(oracle),
        trimesh_stl.export_stl_ascii(oracle).encode("utf-8"),
    ):
        decoded = _core.read_stl(data)
        np.testing.assert_allclose(
            np.asarray(decoded.positions).reshape(-1, 3, 3),
            np.asarray(oracle.triangles),
        )


def test_all_zero_normals_mean_absent():
    triangles = np.zeros((1, 3, 3), np.float32)
    decoded = _core.read_stl(
        _manual_binary(triangles, np.zeros((1, 3), np.float32))
    )
    assert decoded.corner_normals.shape == (0, 3)
    assert not _core._inspect_stl(
        _manual_binary(triangles, np.zeros((1, 3), np.float32))
    )["has_facet_normals"]


@pytest.mark.parametrize("encoding", ["binary", "ascii"])
def test_empty_mesh_roundtrip(encoding):
    mesh = _core.mesh(
        np.empty((0, 3), np.float32),
        np.array([0], np.uint64),
        np.empty(0, np.uint64),
    )
    decoded = _core.read_stl(_core.write_stl(mesh, encoding))
    assert decoded.num_vertices == decoded.num_faces == decoded.num_corners == 0


def test_face_subset_equals_explicit_full_slice():
    data = bytes(_core.write_stl(_triangle_soup()))
    full = _core.read_stl(data)
    part = _core.read_stl_faces(data, 1, 2)
    np.testing.assert_array_equal(part.positions, full.positions[3:6])
    np.testing.assert_array_equal(part.corner_normals, full.corner_normals[3:6])
    assert part.face_offsets.tolist() == [0, 3]
    assert part.face_indices.tolist() == [0, 1, 2]


def test_mmap_equals_bytes_and_decoded_record_owns_storage(tmp_path):
    path = tmp_path / "mapped.stl"
    path.write_bytes(bytes(_core.write_stl(_triangle_soup())))
    expected = _core.read_stl(path.read_bytes())
    with path.open("rb") as stream:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        actual = _core.read_stl(mapped)
        mapped.close()
    path.write_bytes(b"replacement")
    gc.collect()
    np.testing.assert_array_equal(actual.positions, expected.positions)
    np.testing.assert_array_equal(actual.corner_normals, expected.corner_normals)


def test_public_api_detect_read_write_inspect_partial_and_sink_equality(tmp_path):
    mesh = _triangle_soup()
    path = tmp_path / "mesh.stl"
    sceneio.write(mesh, path)
    assert sceneio.detect(path) == "stl"
    decoded = sceneio.read(path)
    np.testing.assert_array_equal(decoded.positions, mesh.positions)
    info = sceneio.inspect(path)
    assert info.format == "stl"
    assert info.shape == (6, 3)
    assert info.metadata["encoding"] == "binary"
    partial = sceneio.read_partial(path, faces=(1, 2))
    np.testing.assert_array_equal(partial.positions, mesh.positions[3:6])
    assert path.read_bytes() == bytes(_core.write_stl(mesh))


def test_direct_file_sink_is_byte_identical_and_chunked(tmp_path):
    mesh = _triangle_soup()
    expected = bytes(_core.write_stl(mesh))
    path = tmp_path / "sink.stl"
    calls = _core._write_to_file(_core.write_stl, mesh, path, _max_chunk=17)
    assert calls > 1
    assert path.read_bytes() == expected


def test_writer_guard_failure_does_not_truncate_destination(tmp_path):
    path = tmp_path / "existing.stl"
    path.write_bytes(b"keep this")
    shared = _core.mesh(
        np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32),
        np.array([0, 3], np.uint64),
        np.array([0, 1, 1], np.uint64),
    )
    with pytest.raises(sceneio.FormatError, match="indexed/shared"):
        sceneio.write(shared, path)
    assert path.read_bytes() == b"keep this"


def test_writer_guards_lossy_mesh_conventions():
    positions = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32)
    offsets = np.array([0, 3], np.uint64)
    indices = np.array([0, 1, 2], np.uint64)
    cases = [
        (
            _core.mesh(
                positions,
                offsets,
                indices,
                vertex_normals=np.ones((3, 3), np.float32),
            ),
            "vertex normals",
        ),
        (
            _core.mesh(
                positions,
                offsets,
                indices,
                vertex_uvs=np.zeros((3, 2), np.float32),
            ),
            "UVs and colors",
        ),
        (
            _core.mesh(
                positions,
                offsets,
                indices,
                corner_normals=np.zeros((3, 3), np.float32),
            ),
            "all-zero",
        ),
        (
            _core.mesh(
                positions,
                offsets,
                indices,
                corner_normals=np.eye(3, dtype=np.float32),
            ),
            "bit-identical",
        ),
        (
            _core.mesh(
                positions,
                np.array([0, 4], np.uint64),
                np.array([0, 1, 2, 0], np.uint64),
            ),
            "distinct vertex",
        ),
        (
            _core.mesh(
                positions,
                offsets,
                np.array([0, 1, 1], np.uint64),
            ),
            "indexed/shared",
        ),
        (
            _core.mesh(
                positions,
                offsets,
                indices,
                coordinate_frame="opengl",
            ),
            "coordinate frame",
        ),
        (
            _core.mesh(
                positions,
                offsets,
                indices,
                materials=_core.material_set(["matte"]),
            ),
            "MaterialSet",
        ),
    ]
    for mesh, message in cases:
        with pytest.raises(ValueError, match=message):
            _core.write_stl(mesh)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "must begin with solid"),
        (b"solid x\n", "missing endsolid"),
        (
            b"solid x\nfacet normal 0 0 nan\n",
            "invalid or out-of-range",
        ),
        (
            b"solid x\nfacet normal 0 0 1\nouter loop\n"
            b"vertex 0 0 0\nvertex 1 0 0\nendloop\n",
            "three vertex",
        ),
        (b"solid x\nendsolid x\nextra\n", "trailing"),
        (b"solid \xff\nendsolid\n", "UTF-8"),
        (b"solid x\0\nendsolid\n", "embedded NUL"),
    ],
)
def test_ascii_malformed_inputs_reject(data, message):
    with pytest.raises(ValueError, match=message):
        _core.read_stl(data)


def test_binary_malformed_inputs_reject():
    triangles = np.zeros((1, 3, 3), np.float32)
    normals = np.zeros((1, 3), np.float32)
    with pytest.raises(ValueError):
        _core.read_stl(_manual_binary(triangles, normals)[:-1])
    with pytest.raises(ValueError, match="attributes/colors"):
        _core.read_stl(_manual_binary(triangles, normals, attributes=(1,)))
    bad = bytearray(_manual_binary(triangles, normals))
    struct.pack_into("<f", bad, 84, np.inf)
    with pytest.raises(ValueError, match="non-finite"):
        _core.read_stl(bytes(bad))


def test_ascii_line_limit_rejects_before_tokenization():
    with pytest.raises(ValueError, match="line exceeds"):
        _core.read_stl(b"solid " + b"x" * (1024 * 1024) + b"\nendsolid\n")


def test_range_validation_and_encoding_guard():
    data = bytes(_core.write_stl(_triangle_soup()))
    with pytest.raises(ValueError, match="non-empty"):
        _core.read_stl_faces(data, 1, 1)
    with pytest.raises(ValueError, match="available extent"):
        _core.read_stl_faces(data, 0, 3)
    with pytest.raises(ValueError, match="encoding"):
        _core.write_stl(_triangle_soup(), "binary_big_endian")


def test_ascii_writer_uses_dot_decimal_under_non_c_numeric_locale():
    previous = locale.setlocale(locale.LC_NUMERIC)
    chosen = None
    for candidate in ("German_Germany.1252", "de_DE.UTF-8", "de_DE"):
        try:
            locale.setlocale(locale.LC_NUMERIC, candidate)
            chosen = candidate
            break
        except locale.Error:
            continue
    if chosen is None:
        pytest.skip("no comma-decimal locale installed")
    try:
        data = bytes(_core.write_stl(_triangle_soup(), "ascii"))
        assert b"1," not in data
        _core.read_stl(data)
    finally:
        locale.setlocale(locale.LC_NUMERIC, previous)
