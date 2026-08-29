"""Generic point-cloud PLY parity, dispatch, partial-read, and guard coverage."""

from __future__ import annotations

import gc
import mmap
import struct
import tracemalloc
from io import BytesIO

import numpy as np
import pytest

import sceneio
from sceneio import _core

_TYPE_INFO = {
    "char": ("b", "i1"),
    "int8": ("b", "i1"),
    "uchar": ("B", "u1"),
    "uint8": ("B", "u1"),
    "short": ("h", "i2"),
    "int16": ("h", "i2"),
    "ushort": ("H", "u2"),
    "uint16": ("H", "u2"),
    "int": ("i", "i4"),
    "int32": ("i", "i4"),
    "uint": ("I", "u4"),
    "uint32": ("I", "u4"),
    "float": ("f", "f4"),
    "float32": ("f", "f4"),
    "double": ("d", "f8"),
    "float64": ("d", "f8"),
}


def _make_ply(encoding, properties, rows, *, suffix=b""):
    header = (
        "ply\n"
        f"format {encoding} 1.0\n"
        f"element vertex {len(rows)}\n"
        + "".join(f"property {kind} {name}\n" for kind, name in properties)
        + "end_header\n"
    ).encode()
    if encoding == "ascii":
        body = "".join(" ".join(map(str, row)) + "\n" for row in rows).encode()
    else:
        order = "<" if encoding == "binary_little_endian" else ">"
        layout = order + "".join(_TYPE_INFO[kind][0] for kind, _ in properties)
        body = b"".join(struct.pack(layout, *row) for row in rows)
    return header + body + suffix


def _oracle(data):
    """Independent NumPy/stdlib parser for the point-only fixtures."""

    stream = BytesIO(data)
    assert stream.readline().rstrip() == b"ply"
    encoding = None
    count = None
    properties = []
    while True:
        tokens = stream.readline().split()
        assert tokens
        if tokens[0] == b"format":
            encoding = tokens[1].decode()
        elif tokens[0] == b"element":
            assert tokens[1] == b"vertex"
            count = int(tokens[2])
        elif tokens[0] == b"property":
            properties.append((tokens[1].decode(), tokens[2].decode()))
        elif tokens[0] == b"end_header":
            break
    assert encoding is not None and count is not None
    if encoding == "ascii":
        rows = []
        for _ in range(count):
            tokens = stream.readline().split()
            assert len(tokens) == len(properties)
            row = []
            for token, (kind, _) in zip(tokens, properties, strict=True):
                dtype = np.dtype(_TYPE_INFO[kind][1])
                row.append(np.array(token.decode(), dtype=dtype).item())
            rows.append(row)
        assert not stream.read().strip()
        return properties, rows
    order = "<" if encoding == "binary_little_endian" else ">"
    dtype = np.dtype(
        [
            (name, order + _TYPE_INFO[kind][1])
            for kind, name in properties
        ]
    )
    values = np.frombuffer(stream.read(), dtype=dtype, count=count)
    return properties, [
        [values[name][row].item() for _, name in properties]
        for row in range(count)
    ]


def _cloud(n=7, *, rgb8=True, rgb16=False, intensity_range="unknown"):
    rng = np.random.default_rng(281)
    positions = rng.standard_normal((n, 3)).astype(np.float32)
    normals = rng.standard_normal((n, 3)).astype(np.float32)
    colors = rng.integers(0, 256, (n, 3), dtype=np.uint8) if rgb8 else None
    colors16 = (
        rng.integers(0, 65536, (n, 3), dtype=np.uint16) if rgb16 else None
    )
    if intensity_range == "u8":
        intensity = rng.integers(0, 256, n).astype(np.float32)
    elif intensity_range == "u16":
        intensity = rng.integers(0, 65536, n).astype(np.float32)
    else:
        intensity = rng.standard_normal(n).astype(np.float32)
    return _core.point_cloud(
        positions,
        colors=colors,
        colors16=colors16,
        normals=normals,
        intensity=intensity,
        intensity_range=intensity_range,
    )


def _assert_cloud_equal(actual, expected):
    assert actual.num_points == expected.num_points
    assert (
        actual.has_rgb,
        actual.has_rgb16,
        actual.has_normals,
        actual.has_intensity,
    ) == (
        expected.has_rgb,
        expected.has_rgb16,
        expected.has_normals,
        expected.has_intensity,
    )
    assert actual.intensity_range == expected.intensity_range
    for name in ("positions", "colors", "colors16", "normals", "intensities"):
        np.testing.assert_array_equal(
            np.asarray(getattr(actual, name)),
            np.asarray(getattr(expected, name)),
        )


@pytest.mark.parametrize(
    "encoding",
    ["ascii", "binary_little_endian", "binary_big_endian"],
)
@pytest.mark.parametrize("intensity_range", ["unknown", "u8", "u16"])
def test_writer_roundtrip_and_independent_oracle(encoding, intensity_range):
    expected = _cloud(
        rgb8=intensity_range != "u16",
        rgb16=intensity_range == "u16",
        intensity_range=intensity_range,
    )
    encoded = bytes(_core.write_ply(expected, encoding))
    actual = _core.read_ply(encoded)
    _assert_cloud_equal(actual, expected)

    properties, rows = _oracle(encoded)
    names = [name for _, name in properties]
    assert names[:6] == ["x", "y", "z", "nx", "ny", "nz"]
    assert names[-1] == "intensity"
    oracle = np.asarray(rows)
    np.testing.assert_array_equal(
        oracle[:, :3].astype(np.float32), np.asarray(expected.positions)
    )
    np.testing.assert_array_equal(
        oracle[:, 3:6].astype(np.float32), np.asarray(expected.normals)
    )
    expected_colors = (
        np.asarray(expected.colors16)
        if expected.has_rgb16
        else np.asarray(expected.colors)
    )
    np.testing.assert_array_equal(
        oracle[:, 6:9].astype(expected_colors.dtype), expected_colors
    )
    np.testing.assert_array_equal(
        oracle[:, 9].astype(np.float32), np.asarray(expected.intensities)
    )


@pytest.mark.parametrize(
    "encoding",
    ["ascii", "binary_little_endian", "binary_big_endian"],
)
def test_writer_preserves_special_float32_values(encoding):
    bits = np.asarray(
        [
            0x00000000,
            0x80000000,
            0x7F800000,
            0xFF800000,
            0x7FC12345,
            0xFFC54321,
        ],
        dtype=np.uint32,
    )
    values = bits.view(np.float32)
    positions = np.resize(values, (6, 3)).copy()
    cloud = _core.point_cloud(positions)
    decoded = _core.read_ply(_core.write_ply(cloud, encoding))
    actual = np.asarray(decoded.positions)
    if encoding != "ascii":
        np.testing.assert_array_equal(
            actual.view(np.uint32), positions.view(np.uint32)
        )
        return
    finite_or_inf = ~np.isnan(positions)
    np.testing.assert_array_equal(
        actual.view(np.uint32)[finite_or_inf],
        positions.view(np.uint32)[finite_or_inf],
    )
    assert np.array_equal(np.isnan(actual), np.isnan(positions))
    assert np.array_equal(np.signbit(actual), np.signbit(positions))


@pytest.mark.parametrize(
    ("scalar", "values"),
    [
        ("char", (-7, 8)),
        ("uint8", (7, 8)),
        ("int16", (-700, 800)),
        ("ushort", (700, 800)),
        ("int32", (-70000, 80000)),
        ("uint32", (70000, 80000)),
        ("float32", (-1.25, 2.5)),
        ("double", (-1.25, 2.5)),
    ],
)
@pytest.mark.parametrize(
    "encoding",
    ["ascii", "binary_little_endian", "binary_big_endian"],
)
def test_reader_accepts_every_standard_scalar_family(scalar, values, encoding):
    properties = [(scalar, "x"), ("float", "z"), ("float", "y")]
    rows = [(values[0], 3.0, 2.0), (values[1], 6.0, 5.0)]
    cloud = _core.read_ply(_make_ply(encoding, properties, rows))
    np.testing.assert_array_equal(
        np.asarray(cloud.positions),
        np.asarray([[values[0], 2, 3], [values[1], 5, 6]], dtype=np.float32),
    )


@pytest.mark.parametrize(
    "encoding",
    ["ascii", "binary_little_endian", "binary_big_endian"],
)
def test_property_order_rgb16_normals_intensity_and_nan(encoding):
    properties = [
        ("uint16", "blue"),
        ("double", "z"),
        ("float", "nx"),
        ("uint16", "red"),
        ("float", "x"),
        ("float", "nz"),
        ("uint16", "green"),
        ("float", "y"),
        ("float", "ny"),
        ("ushort", "intensity"),
    ]
    rows = [(3, 9.0, 0.1, 1, "nan", 0.3, 2, 8.0, 0.2, 65535)]
    if encoding != "ascii":
        rows = [(3, 9.0, 0.1, 1, np.nan, 0.3, 2, 8.0, 0.2, 65535)]
    cloud = _core.read_ply(_make_ply(encoding, properties, rows))
    assert np.isnan(np.asarray(cloud.positions)[0, 0])
    np.testing.assert_array_equal(cloud.colors16, [[1, 2, 3]])
    np.testing.assert_allclose(cloud.normals, [[0.1, 0.2, 0.3]])
    np.testing.assert_array_equal(cloud.intensities, [65535])
    assert cloud.intensity_range == "u16"


def test_open3d_reads_sceneio_and_sceneio_reads_open3d(tmp_path):
    o3d = pytest.importorskip("open3d")
    expected = _cloud(rgb8=True, intensity_range="unknown")
    for encoding in ("ascii", "binary_little_endian", "binary_big_endian"):
        path = tmp_path / f"sceneio-{encoding}.ply"
        path.write_bytes(bytes(_core.write_ply(expected, encoding)))
        oracle = o3d.io.read_point_cloud(str(path))
        np.testing.assert_allclose(np.asarray(oracle.points), expected.positions)
        np.testing.assert_allclose(np.asarray(oracle.normals), expected.normals)
        np.testing.assert_allclose(
            np.asarray(oracle.colors),
            np.asarray(expected.colors, dtype=np.float64) / 255.0,
            atol=1 / 255,
        )

    oracle = o3d.geometry.PointCloud()
    oracle.points = o3d.utility.Vector3dVector(
        np.asarray(expected.positions, dtype=np.float64)
    )
    oracle.normals = o3d.utility.Vector3dVector(
        np.asarray(expected.normals, dtype=np.float64)
    )
    oracle.colors = o3d.utility.Vector3dVector(
        np.asarray(expected.colors, dtype=np.float64) / 255.0
    )
    path = tmp_path / "open3d.ply"
    assert o3d.io.write_point_cloud(
        str(path), oracle, write_ascii=False, compressed=False
    )
    actual = sceneio.read(path)
    np.testing.assert_allclose(actual.positions, expected.positions)
    np.testing.assert_allclose(actual.normals, expected.normals)
    np.testing.assert_allclose(actual.colors, expected.colors, atol=1)


def test_binary_point_ranges_equal_full_slice_and_ascii_refuses():
    expected = _cloud(n=19, rgb8=False, rgb16=True, intensity_range="u16")
    for encoding in ("binary_little_endian", "binary_big_endian"):
        encoded = bytes(_core.write_ply(expected, encoding))
        selected = _core.read_ply_points(encoded, 4, 15)
        assert selected.num_points == 11
        for name in ("positions", "colors16", "normals", "intensities"):
            np.testing.assert_array_equal(
                np.asarray(getattr(selected, name)),
                np.asarray(getattr(expected, name))[4:15],
            )
    with pytest.raises(ValueError, match="binary fixed-record"):
        _core.read_ply_points(bytes(_core.write_ply(expected, "ascii")), 4, 15)


def test_public_schema_detection_inspection_and_dispatch(tmp_path):
    cloud = _cloud()
    path = tmp_path / "points.ply"
    sceneio.write(cloud, path)
    assert sceneio.detect(path) == "ply"
    decoded = sceneio.read(path)
    _assert_cloud_equal(decoded, cloud)
    selected = sceneio.read_partial(path, points=(2, 6))
    assert selected.num_points == 4

    info = sceneio.inspect(path)
    assert (info.format, info.shape, info.dtype, info.count) == (
        "ply",
        (cloud.num_points, 3),
        "float32",
        cloud.num_points,
    )
    assert info.metadata["encoding"] == "binary_little_endian"
    assert info.metadata["has_normals"]
    assert info.metadata["color_dtype"] == "uint8"
    assert info.metadata["properties"][-1] == "intensity"

    extensionless = tmp_path / "points"
    extensionless.write_bytes(path.read_bytes())
    assert sceneio.detect(extensionless) == "ply"


def test_inspection_reads_only_the_header_for_large_binary_payload(tmp_path):
    header = (
        b"ply\nformat binary_little_endian 1.0\n"
        b"element vertex 4194304\n"
        b"property float x\nproperty float y\nproperty float z\nend_header\n"
    )
    path = tmp_path / "sparse-large.ply"
    with path.open("wb") as stream:
        stream.write(header)
        stream.truncate(len(header) + 4194304 * 12)
    tracemalloc.start()
    info = sceneio.inspect(path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert (info.count, info.byte_size) == (4194304, len(header) + 4194304 * 12)
    assert peak < 256 * 1024


def test_detection_dispatches_gaussian_and_mesh_schemas_authoritatively(tmp_path):
    rng = np.random.default_rng(11)
    gaussian = _core.gaussian_cloud(
        rng.standard_normal((2, 3)).astype(np.float32),
        rng.standard_normal((2, 3)).astype(np.float32),
        rng.standard_normal((2, 4)).astype(np.float32),
        rng.standard_normal(2).astype(np.float32),
        rng.standard_normal((2, 3)).astype(np.float32),
    )
    gaussian_path = tmp_path / "gaussian.ply"
    gaussian_path.write_bytes(bytes(_core.write_gaussian_ply(gaussian)))
    assert sceneio.detect(gaussian_path) == "gaussian_ply"
    decoded = sceneio.read(gaussian_path)
    assert isinstance(decoded, _core.GaussianCloud)
    np.testing.assert_array_equal(decoded.means, gaussian.means)

    mesh = tmp_path / "mesh.ply"
    mesh.write_bytes(
        b"ply\nformat ascii 1.0\nelement vertex 3\n"
        b"property float x\nproperty float y\nproperty float z\n"
        b"element face 1\nproperty list uchar int vertex_indices\n"
        b"end_header\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n"
    )
    assert sceneio.detect(mesh) == "ply_mesh"
    decoded_mesh = sceneio.read(mesh)
    assert isinstance(decoded_mesh, _core.Mesh)
    np.testing.assert_array_equal(
        decoded_mesh.positions,
        [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
    )
    np.testing.assert_array_equal(decoded_mesh.face_offsets, [0, 3])
    np.testing.assert_array_equal(decoded_mesh.face_indices, [0, 1, 2])


def test_detection_refuses_hybrid_gaussian_schema_instead_of_dropping_fields(
    tmp_path,
):
    rng = np.random.default_rng(12)
    gaussian = _core.gaussian_cloud(
        rng.standard_normal((1, 3)).astype(np.float32),
        rng.standard_normal((1, 3)).astype(np.float32),
        rng.standard_normal((1, 4)).astype(np.float32),
        rng.standard_normal(1).astype(np.float32),
        rng.standard_normal((1, 3)).astype(np.float32),
    )
    encoded = bytes(_core.write_gaussian_ply(gaussian))
    header_end = encoded.index(b"end_header\n")
    hybrid = (
        encoded[:header_end]
        + b"property float temperature\n"
        + encoded[header_end:]
        + struct.pack("<f", 1.0)
    )
    path = tmp_path / "hybrid.ply"
    path.write_bytes(hybrid)
    with pytest.raises(
        sceneio.FormatError, match="unsupported Gaussian vertex property"
    ):
        sceneio.detect(path)


@pytest.mark.parametrize(
    ("properties", "message"),
    [
        ([("float", "x"), ("float", "y")], "missing property 'z'"),
        (
            [
                ("float", "x"),
                ("float", "y"),
                ("float", "z"),
                ("float", "nx"),
            ],
            "normals require",
        ),
        (
            [
                ("float", "x"),
                ("float", "y"),
                ("float", "z"),
                ("uchar", "red"),
                ("uchar", "green"),
            ],
            "colors require",
        ),
        (
            [
                ("float", "x"),
                ("float", "y"),
                ("float", "z"),
                ("float", "temperature"),
            ],
            "unsupported vertex property",
        ),
    ],
)
def test_reader_rejects_unrepresentable_schemas(properties, message):
    with pytest.raises(ValueError, match=message):
        _core.read_ply(
            _make_ply("binary_little_endian", properties, [(0,) * len(properties)])
        )


def test_reader_rejects_lists_nonvertices_mixed_rgb_and_duplicate_properties():
    cases = [
        (
            b"ply\nformat ascii 1.0\nelement vertex 1\n"
            b"property float x\nproperty float y\nproperty float z\n"
            b"property list uchar float samples\nend_header\n0 0 0 0\n",
            "list-valued",
        ),
        (
            b"ply\nformat ascii 1.0\nelement vertex 0\n"
            b"property float x\nproperty float y\nproperty float z\n"
            b"element edge 0\nproperty int vertex1\nend_header\n",
            "non-vertex",
        ),
        (
            _make_ply(
                "ascii",
                [
                    ("float", "x"),
                    ("float", "y"),
                    ("float", "z"),
                    ("uchar", "red"),
                    ("ushort", "green"),
                    ("uchar", "blue"),
                ],
                [(0, 0, 0, 1, 2, 3)],
            ),
            "uniformly",
        ),
        (
            b"ply\nformat ascii 1.0\nelement vertex 0\n"
            b"property float x\nproperty float x\nproperty float z\nend_header\n",
            "duplicate property",
        ),
    ]
    for payload, message in cases:
        with pytest.raises(ValueError, match=message):
            _core.read_ply(payload)


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"ply",
        b"ply\nend_header\n",
        b"ply\nformat ascii 2.0\nelement vertex 0\nend_header\n",
        b"ply\nformat ascii 1.0\nformat ascii 1.0\n"
        b"element vertex 0\nend_header\n",
        b"ply\nformat ascii 1.0\nelement vertex -1\nend_header\n",
        b"ply\nformat ascii 1.0\nelement vertex 1\n"
        b"property float x\nproperty float y\nproperty float z\nend_header\n0 0\n",
    ],
)
def test_malformed_headers_and_truncated_ascii_raise(payload):
    with pytest.raises(ValueError):
        _core.read_ply(payload)


def test_inspection_rejects_impossible_ascii_count_without_scanning_body(
    tmp_path,
):
    path = tmp_path / "truncated-ascii.ply"
    path.write_bytes(
        b"ply\nformat ascii 1.0\nelement vertex 2\n"
        b"property float x\nproperty float y\nproperty float z\n"
        b"end_header\n0 0\n"
    )
    with pytest.raises(sceneio.FormatError, match="count exceeds payload"):
        sceneio.inspect(path, format="ply")


def test_binary_truncation_trailing_and_float64_overflow_raise():
    payload = _make_ply(
        "binary_little_endian",
        [("float", "x"), ("float", "y"), ("float", "z")],
        [(1, 2, 3)],
    )
    with pytest.raises(ValueError, match="truncated"):
        _core.read_ply(payload[:-1])
    with pytest.raises(ValueError, match="trailing"):
        _core.read_ply(payload + b"x")
    overflow = _make_ply(
        "binary_little_endian",
        [("double", "x"), ("float", "y"), ("float", "z")],
        [(1e300, 2, 3)],
    )
    with pytest.raises(ValueError, match="float32 range"):
        _core.read_ply(overflow)


@pytest.mark.parametrize(
    "encoding",
    ["ascii", "binary_little_endian", "binary_big_endian"],
)
def test_declared_count_bombs_raise_before_allocation(encoding):
    payload = (
        "ply\n"
        f"format {encoding} 1.0\n"
        f"element vertex {2**63 - 1}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "end_header\n"
    ).encode()
    with pytest.raises(ValueError, match=r"count|payload|overflows"):
        _core.read_ply(payload)


def test_header_and_ascii_token_limits_are_bounded():
    oversized_header = (
        b"ply\nformat ascii 1.0\ncomment "
        + b"x" * (1024 * 1024)
        + b"\nelement vertex 0\nproperty float x\n"
        b"property float y\nproperty float z\nend_header\n"
    )
    with pytest.raises(ValueError, match="header exceeds"):
        _core.read_ply(oversized_header)
    oversized_token = (
        b"ply\nformat ascii 1.0\nelement vertex 1\n"
        b"property float x\nproperty float y\nproperty float z\nend_header\n"
        + b"1" * (1024 * 1024 + 1)
        + b" 0 0\n"
    )
    with pytest.raises(ValueError, match="token exceeds"):
        _core.read_ply(oversized_token)


def test_empty_cloud_and_invalid_ranges():
    empty = _core.point_cloud(np.empty((0, 3), dtype=np.float32))
    for encoding in ("ascii", "binary_little_endian", "binary_big_endian"):
        decoded = _core.read_ply(_core.write_ply(empty, encoding))
        assert decoded.num_points == 0
    payload = _core.write_ply(_cloud())
    for bounds in ((0, 0), (4, 3), (0, 99)):
        with pytest.raises(ValueError):
            _core.read_ply_points(payload, *bounds)


def test_writer_refuses_unrepresentable_fields_and_metadata():
    positions = np.zeros((2, 3), dtype=np.float32)
    colors = np.zeros((2, 3), dtype=np.uint8)
    colors16 = np.zeros((2, 3), dtype=np.uint16)
    bad = [
        _core.point_cloud(
            positions,
            colors=colors,
            colors16=colors16,
        ),
        _core.point_cloud(positions, coordinate_frame="enu"),
        _core.point_cloud(positions, scale_to_meters=0.01),
        _core.point_cloud(
            positions, origin=np.asarray([1, 0, 0], dtype=np.float64)
        ),
        _core.point_cloud(
            positions,
            intensity=np.asarray([0.25, 0.5], dtype=np.float32),
            intensity_range="unit",
        ),
        _core.point_cloud(
            positions,
            intensity=np.asarray([1.5, 2], dtype=np.float32),
            intensity_range="u8",
        ),
        _core.point_cloud(positions, intensity_range="u16"),
    ]
    for cloud in bad:
        with pytest.raises(ValueError):
            _core.write_ply(cloud)
    with pytest.raises(ValueError, match="encoding must be"):
        _core.write_ply(_core.point_cloud(positions), "compressed")


def test_mmap_equals_bytes_lifetime_mutation_isolation_and_memory(tmp_path):
    cloud = _cloud(n=200_000)
    payload = bytes(_core.write_ply(cloud))
    path = tmp_path / "large.ply"
    path.write_bytes(payload)
    expected = _core.read_ply(payload)
    with (
        path.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
    ):
        tracemalloc.start()
        actual = _core.read_ply(mapped)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    gc.collect()
    _assert_cloud_equal(actual, expected)
    assert peak < len(payload) + 1024 * 1024

    copied = np.asarray(actual.positions).copy()
    path.write_bytes(bytes(_core.write_ply(_cloud(n=200_000))))
    np.testing.assert_array_equal(actual.positions, copied)


def test_file_sink_is_byte_identical_and_guard_does_not_truncate(tmp_path):
    cloud = _cloud()
    expected = bytes(_core.write_ply(cloud))
    path = tmp_path / "points.ply"
    sceneio.write(cloud, path)
    assert path.read_bytes() == expected
    _core._write_to_file(_core.write_ply, cloud, path)
    assert path.read_bytes() == expected

    path.write_bytes(b"keep")
    bad = _core.point_cloud(
        np.zeros((1, 3), dtype=np.float32), coordinate_frame="enu"
    )
    with pytest.raises(ValueError):
        _core._write_to_file(_core.write_ply, bad, path)
    assert path.read_bytes() == b"keep"
