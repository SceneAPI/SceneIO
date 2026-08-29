"""Independent parity, fidelity, guard, mmap, partial, and sink tests for OFF."""

from __future__ import annotations

import gc
import io
import locale
import mmap

import numpy as np
import pytest
import trimesh

import sceneio
from sceneio import _core


def _mesh(*, attributes: bool = True):
    positions = np.array(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0.5, 0.5, 1]],
        np.float32,
    )
    kwargs = {}
    if attributes:
        kwargs.update(
            vertex_normals=np.array([[0, 0, 1]] * 5, np.float32),
            vertex_uvs=np.array(
                [[0, 0], [1, 0], [1, 1], [0, 1], [0.5, 0.5]],
                np.float32,
            ),
            vertex_colors=np.array(
                [
                    [255, 0, 0, 255],
                    [0, 255, 0, 255],
                    [0, 0, 255, 255],
                    [255, 255, 255, 255],
                    [128, 64, 0, 255],
                ],
                np.uint8,
            ),
        )
    return _core.mesh(
        positions,
        np.array([0, 4, 7], np.uint64),
        np.array([0, 1, 2, 3, 0, 3, 4], np.uint64),
        **kwargs,
    )


def _variant_fixture(
    variant: str,
    *,
    integer_colors: bool = True,
) -> bytes:
    normals = " 0 0 1" if "N" in variant.removesuffix("OFF") else ""
    if "C" in variant.removesuffix("OFF"):
        colors = (
            (" 128 64 0 255", " 0 255 255 255", " 255 0 255 255")
            if integer_colors
            else (
                " 0.501960814 0.250980407 0 1",
                " 0 1 1 1",
                " 1 0 1 1",
            )
        )
    else:
        colors = ("", "", "")
    uvs = (" 0 0", " 1 0", " 0 1") if variant.startswith("ST") else ("", "", "")
    vertices = [
        f"0 0 0{normals}{colors[0]}{uvs[0]}",
        f"1 0 0{normals}{colors[1]}{uvs[1]}",
        f"0 1 0{normals}{colors[2]}{uvs[2]}",
    ]
    return (f"{variant}\n3 1 3\n" + "\n".join(vertices) + "\n3 0 1 2\n").encode()


def _assert_variant(decoded, variant):
    prefix = variant.removesuffix("OFF")
    np.testing.assert_array_equal(
        decoded.positions, [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
    )
    assert decoded.face_offsets.tolist() == [0, 3]
    assert decoded.face_indices.tolist() == [0, 1, 2]
    if "N" in prefix:
        np.testing.assert_array_equal(decoded.vertex_normals, [[0, 0, 1]] * 3)
    else:
        assert decoded.vertex_normals.shape == (0, 3)
    if "C" in prefix:
        np.testing.assert_array_equal(
            decoded.vertex_colors,
            [[128, 64, 0, 255], [0, 255, 255, 255], [255, 0, 255, 255]],
        )
    else:
        assert decoded.vertex_colors.shape == (0, 4)
    if prefix.startswith("ST"):
        np.testing.assert_array_equal(decoded.vertex_uvs, [[0, 0], [1, 0], [0, 1]])
    else:
        assert decoded.vertex_uvs.shape == (0, 2)


@pytest.mark.parametrize(
    "variant",
    [
        "OFF",
        "NOFF",
        "COFF",
        "CNOFF",
        "STOFF",
        "STNOFF",
        "STCOFF",
        "STCNOFF",
    ],
)
def test_all_ascii_vertex_variants_decode_independently(variant):
    data = _variant_fixture(variant)
    decoded = _core.read_off(data)
    _assert_variant(decoded, variant)
    info = _core._inspect_off(data)
    assert info["variant"] == variant
    assert info["num_vertices"] == 3
    assert info["num_faces"] == 1
    assert info["num_corners"] == 3
    assert info["declared_edges"] == 3


@pytest.mark.parametrize("integer_colors", [True, False])
def test_integer_and_exact_normalized_rgba_modes(integer_colors):
    decoded = _core.read_off(
        _variant_fixture("COFF", integer_colors=integer_colors)
    )
    np.testing.assert_array_equal(
        decoded.vertex_colors,
        [[128, 64, 0, 255], [0, 255, 255, 255], [255, 0, 255, 255]],
    )


def test_writer_roundtrips_every_rgba8_channel_value_exactly():
    count = 256
    colors = np.repeat(
        np.arange(count, dtype=np.uint8)[:, None],
        4,
        axis=1,
    )
    mesh = _core.mesh(
        np.zeros((count, 3), np.float32),
        np.array([0, 3], np.uint64),
        np.array([0, 1, 2], np.uint64),
        vertex_colors=colors,
    )
    np.testing.assert_array_equal(
        _core.read_off(_core.write_off(mesh)).vertex_colors,
        colors,
    )


def test_empty_mesh_roundtrip():
    mesh = _core.mesh(
        np.empty((0, 3), np.float32),
        np.array([0], np.uint64),
        np.empty(0, np.uint64),
    )
    decoded = _core.read_off(_core.write_off(mesh))
    assert decoded.num_vertices == decoded.num_faces == decoded.num_corners == 0


def test_polygon_boundaries_and_header_inline_counts_are_preserved():
    data = b"""# comment
OFF 5 2 0
0 0 0
1 0 0
1 1 0
0 1 0
0 0 1
4 0 1 2 3
3 0 3 4
"""
    decoded = _core.read_off(data)
    assert decoded.face_offsets.tolist() == [0, 4, 7]
    assert decoded.face_indices.tolist() == [0, 1, 2, 3, 0, 3, 4]


def test_writer_uses_canonical_variant_order_and_independent_tokens():
    mesh = _mesh()
    text = bytes(_core.write_off(mesh)).decode("ascii")
    lines = text.splitlines()
    assert lines[0] == "STCNOFF"
    assert lines[1] == "5 2 0"
    assert len(lines[2].split()) == 12
    assert lines[-2:] == ["4 0 1 2 3", "3 0 3 4"]
    decoded = _core.read_off(text.encode())
    for name in (
        "positions",
        "face_offsets",
        "face_indices",
        "vertex_normals",
        "vertex_uvs",
        "vertex_colors",
    ):
        np.testing.assert_array_equal(getattr(decoded, name), getattr(mesh, name))


@pytest.mark.parametrize("normals", [False, True])
@pytest.mark.parametrize("colors", [False, True])
@pytest.mark.parametrize("uvs", [False, True])
def test_writer_selects_each_vertex_variant(normals, colors, uvs):
    positions = np.array(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        np.float32,
    )
    kwargs = {}
    if normals:
        kwargs["vertex_normals"] = np.array([[0, 0, 1]] * 3, np.float32)
    if colors:
        kwargs["vertex_colors"] = np.array(
            [[255, 0, 0, 255], [0, 255, 0, 255], [0, 0, 255, 255]],
            np.uint8,
        )
    if uvs:
        kwargs["vertex_uvs"] = np.array([[0, 0], [1, 0], [0, 1]], np.float32)
    mesh = _core.mesh(
        positions,
        np.array([0, 3], np.uint64),
        np.array([0, 1, 2], np.uint64),
        **kwargs,
    )
    expected = ("ST" if uvs else "") + ("C" if colors else "")
    expected += ("N" if normals else "") + "OFF"
    data = bytes(_core.write_off(mesh))
    assert data.splitlines()[0].decode() == expected
    decoded = _core.read_off(data)
    for name in ("vertex_normals", "vertex_uvs", "vertex_colors"):
        np.testing.assert_array_equal(getattr(decoded, name), getattr(mesh, name))


def test_trimesh_reads_ours_and_ours_reads_trimesh():
    mesh = _mesh(attributes=False)
    ours = bytes(_core.write_off(mesh))
    oracle = trimesh.load_mesh(
        file_obj=io.BytesIO(ours), file_type="off", process=False
    )
    np.testing.assert_allclose(np.asarray(oracle.vertices), mesh.positions)
    assert {frozenset(face) for face in np.asarray(oracle.faces)} == {
        frozenset((0, 1, 2)),
        frozenset((0, 2, 3)),
        frozenset((0, 3, 4)),
    }

    oracle_source = trimesh.Trimesh(
        vertices=np.asarray(mesh.positions),
        faces=np.array([[0, 1, 4], [1, 2, 4]], np.int64),
        process=False,
    )
    exported = oracle_source.export(file_type="off")
    if isinstance(exported, str):
        exported = exported.encode()
    decoded = _core.read_off(exported)
    np.testing.assert_allclose(decoded.positions, oracle_source.vertices)
    np.testing.assert_array_equal(decoded.face_indices.reshape(-1, 3), oracle_source.faces)


def test_face_subset_equals_full_slice_and_retains_vertex_domain():
    data = bytes(_core.write_off(_mesh()))
    full = _core.read_off(data)
    part = _core.read_off_faces(data, 1, 2)
    for name in ("positions", "vertex_normals", "vertex_uvs", "vertex_colors"):
        np.testing.assert_array_equal(getattr(part, name), getattr(full, name))
    assert part.face_offsets.tolist() == [0, 3]
    np.testing.assert_array_equal(part.face_indices, full.face_indices[4:7])


def test_mmap_equals_bytes_and_decoded_record_owns_storage(tmp_path):
    path = tmp_path / "mapped.off"
    path.write_bytes(bytes(_core.write_off(_mesh())))
    expected = _core.read_off(path.read_bytes())
    with path.open("rb") as stream:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        actual = _core.read_off(mapped)
        mapped.close()
    path.write_bytes(b"replacement")
    gc.collect()
    for name in ("positions", "face_offsets", "face_indices", "vertex_colors"):
        np.testing.assert_array_equal(getattr(actual, name), getattr(expected, name))


def test_public_api_detect_read_write_inspect_partial_and_sink_equality(tmp_path):
    mesh = _mesh()
    path = tmp_path / "mesh.off"
    sceneio.write(mesh, path)
    assert sceneio.detect(path) == "off"
    decoded = sceneio.read(path)
    np.testing.assert_array_equal(decoded.face_offsets, mesh.face_offsets)
    info = sceneio.inspect(path)
    assert info.format == "off"
    assert info.shape == (5, 3)
    assert info.metadata["variant"] == "STCNOFF"
    partial = sceneio.read_partial(path, faces=(1, 2))
    assert partial.face_indices.tolist() == [0, 3, 4]
    assert path.read_bytes() == bytes(_core.write_off(mesh))


def test_direct_file_sink_is_byte_identical_and_chunked(tmp_path):
    mesh = _mesh()
    expected = bytes(_core.write_off(mesh))
    path = tmp_path / "sink.off"
    calls = _core._write_to_file(_core.write_off, mesh, path, _max_chunk=13)
    assert calls > 1
    assert path.read_bytes() == expected


def test_writer_guard_failure_does_not_truncate_destination(tmp_path):
    path = tmp_path / "existing.off"
    path.write_bytes(b"keep this")
    incompatible = _core.mesh(
        np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32),
        np.array([0, 3], np.uint64),
        np.array([0, 1, 2], np.uint64),
        coordinate_frame="opengl",
    )
    with pytest.raises(sceneio.FormatError, match="coordinate frame"):
        sceneio.write(incompatible, path)
    assert path.read_bytes() == b"keep this"


def test_writer_guards_unrepresentable_mesh_domains():
    base = _mesh(attributes=False)
    positions = np.asarray(base.positions)
    offsets = np.asarray(base.face_offsets)
    indices = np.asarray(base.face_indices)
    cases = [
        (
            _core.mesh(
                positions,
                offsets,
                indices,
                corner_normals=np.zeros((7, 3), np.float32),
            ),
            "corner-domain",
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
                primitive_offsets=np.array([0, 1, 2], np.uint64),
            ),
            "multiple primitive",
        ),
        (
            _core.mesh(
                positions,
                offsets,
                indices,
                face_smoothing_groups=np.ones(2, np.uint32),
            ),
            "smoothing",
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
            _core.write_off(mesh)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "empty"),
        (b"NCOFF\n0 0 0\n", "unsupported header"),
        (b"OFF BINARY\n", "counts"),
        (b"4OFF\n0 0 0\n", "unsupported header"),
        (b"nOFF\n0 0 0\n", "unsupported header"),
        (b"OFF\n3 1 0\n0 0 0\n1 0 0\n", "truncated vertex"),
        (
            b"OFF\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n3 0 1 3\n",
            "outside the vertex domain",
        ),
        (
            b"OFF\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n3 0 -1 2\n",
            "nonnegative integer",
        ),
        (
            b"OFF\n3 1 0\n0 0 nan\n1 0 0\n0 1 0\n3 0 1 2\n",
            "invalid or out-of-range",
        ),
        (
            b"OFF\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n2 0 1\n",
            "at least three",
        ),
        (
            b"OFF\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2 255 0 0\n",
            "face colors",
        ),
        (
            b"OFF\n3 1 0\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\nextra\n",
            "trailing",
        ),
        (b"OFF\n999999999 0 0\n", "input extent"),
        (b"OFF\n0 0 0\n\0", "embedded NUL"),
        (b"OFF\n0 0 0\n\xff", "UTF-8"),
    ],
)
def test_malformed_inputs_reject(data, message):
    with pytest.raises(ValueError, match=message):
        _core.read_off(data)


@pytest.mark.parametrize(
    "color",
    [
        "256 0 0 255",
        "-1 0 0 255",
        "0.1 0 0 1",
        "1.1 0 0 1",
    ],
)
def test_unrepresentable_vertex_colors_reject(color):
    data = (
        "COFF\n3 1 0\n"
        f"0 0 0 {color}\n"
        "1 0 0 0 0 0 255\n"
        "0 1 0 0 0 0 255\n"
        "3 0 1 2\n"
    ).encode()
    with pytest.raises(ValueError, match="color"):
        _core.read_off(data)


def test_ascii_line_limit_rejects_before_tokenization():
    with pytest.raises(ValueError, match="line exceeds"):
        _core.read_off(b"#" + b"x" * (1024 * 1024) + b"\nOFF\n0 0 0\n")


def test_writer_rejects_face_record_beyond_its_reader_limit():
    corners = 525_000
    mesh = _core.mesh(
        np.zeros((1, 3), np.float32),
        np.array([0, corners], np.uint64),
        np.zeros(corners, np.uint64),
    )
    with pytest.raises(ValueError, match="1 MiB parser limit"):
        _core.write_off(mesh)


def test_range_validation():
    data = bytes(_core.write_off(_mesh()))
    with pytest.raises(ValueError, match="non-empty"):
        _core.read_off_faces(data, 1, 1)
    with pytest.raises(ValueError, match="available extent"):
        _core.read_off_faces(data, 0, 3)


def test_writer_uses_dot_decimal_under_non_c_numeric_locale():
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
        data = bytes(_core.write_off(_mesh()))
        assert b"0,5" not in data
        _core.read_off(data)
    finally:
        locale.setlocale(locale.LC_NUMERIC, previous)
