"""PCD 0.7 parity, compressed-storage, metadata, and hardening coverage."""

from __future__ import annotations

import gc
import mmap
import struct
import tracemalloc

import numpy as np
import pytest

import sceneio
from sceneio import _core

_STRUCT = {
    ("I", 1): "b",
    ("I", 2): "h",
    ("I", 4): "i",
    ("I", 8): "q",
    ("U", 1): "B",
    ("U", 2): "H",
    ("U", 4): "I",
    ("U", 8): "Q",
    ("F", 4): "f",
    ("F", 8): "d",
}


def _lzf_literal(data: bytes) -> bytes:
    output = bytearray()
    for offset in range(0, len(data), 32):
        chunk = data[offset : offset + 32]
        output.append(len(chunk) - 1)
        output.extend(chunk)
    return bytes(output)


def _lzf_decompress(data: bytes, expected: int) -> bytes:
    """Independent stdlib implementation of the documented LZF token stream."""

    output = bytearray()
    cursor = 0
    while cursor < len(data):
        control = data[cursor]
        cursor += 1
        if control < 32:
            length = control + 1
            assert cursor + length <= len(data)
            output.extend(data[cursor : cursor + length])
            cursor += length
            continue
        length = control >> 5
        distance = (control & 0x1F) << 8
        if length == 7:
            assert cursor < len(data)
            length += data[cursor]
            cursor += 1
        assert cursor < len(data)
        distance += data[cursor] + 1
        cursor += 1
        length += 2
        assert distance <= len(output)
        for _ in range(length):
            output.append(output[-distance])
    assert len(output) == expected
    return bytes(output)


def _make_pcd(
    storage,
    fields,
    rows,
    *,
    width=None,
    height=1,
    viewpoint=(0, 0, 0, 1, 0, 0, 0),
    suffix=b"",
    compressed_payload=None,
):
    width = len(rows) if width is None else width
    header = (
        "# .PCD v0.7 - Point Cloud Data file format\n"
        "VERSION .7\n"
        f"FIELDS {' '.join(name for name, _, _ in fields)}\n"
        f"SIZE {' '.join(str(size) for _, size, _ in fields)}\n"
        f"TYPE {' '.join(kind for _, _, kind in fields)}\n"
        f"COUNT {' '.join('1' for _ in fields)}\n"
        f"WIDTH {width}\n"
        f"HEIGHT {height}\n"
        f"VIEWPOINT {' '.join(map(str, viewpoint))}\n"
        f"POINTS {len(rows)}\n"
        f"DATA {storage}\n"
    ).encode()
    if storage == "ascii":
        body = b"".join(
            (" ".join(map(str, row)) + "\n").encode() for row in rows
        )
    else:
        layouts = [_STRUCT[(kind, size)] for _, size, kind in fields]
        aos = b"".join(
            struct.pack("<" + "".join(layouts), *row) for row in rows
        )
        if storage == "binary":
            body = aos
        else:
            field_offsets = np.cumsum([0, *(size for _, size, _ in fields)])
            stride = int(field_offsets[-1])
            soa = b"".join(
                b"".join(
                    aos[row * stride + field_offsets[index] : row * stride + field_offsets[index + 1]]
                    for row in range(len(rows))
                )
                for index in range(len(fields))
            )
            compressed = (
                _lzf_literal(soa)
                if compressed_payload is None
                else compressed_payload
            )
            body = struct.pack("<II", len(compressed), len(soa)) + compressed
    return header + body + suffix


def _oracle(data):
    """Independent PCD reader for the canonical writer schema."""

    lines = data.splitlines(keepends=True)
    headers = {}
    header_size = 0
    for line in lines:
        header_size += len(line)
        tokens = line.strip().split()
        if not tokens or tokens[0] == b"#":
            continue
        headers[tokens[0].decode()] = [token.decode() for token in tokens[1:]]
        if tokens[0] == b"DATA":
            break
    fields = headers["FIELDS"]
    sizes = [int(value) for value in headers["SIZE"]]
    kinds = headers["TYPE"]
    count = int(headers["POINTS"][0])
    storage = headers["DATA"][0]
    formats = [_STRUCT[item] for item in zip(kinds, sizes, strict=True)]
    body = data[header_size:]
    if storage == "ascii":
        tokens = body.split()
        assert len(tokens) == count * len(fields)
        rows = []
        for row in range(count):
            values = []
            for column, (kind, _size) in enumerate(
                zip(kinds, sizes, strict=True)
            ):
                token = tokens[row * len(fields) + column]
                values.append(
                    float(token) if kind == "F" else int(token)
                )
            rows.append(values)
    else:
        raw_size = count * sum(sizes)
        if storage == "binary_compressed":
            compressed_size, uncompressed_size = struct.unpack_from("<II", body)
            assert uncompressed_size == raw_size
            soa = _lzf_decompress(
                body[8 : 8 + compressed_size], uncompressed_size
            )
            offsets = np.cumsum([0, *(size * count for size in sizes)])
            rows = []
            for row in range(count):
                values = []
                for column, (size, layout) in enumerate(
                    zip(sizes, formats, strict=True)
                ):
                    start = int(offsets[column]) + row * size
                    values.append(struct.unpack_from("<" + layout, soa, start)[0])
                rows.append(values)
        else:
            layout = "<" + "".join(formats)
            stride = struct.calcsize(layout)
            assert len(body) == count * stride
            rows = [
                list(struct.unpack_from(layout, body, row * stride))
                for row in range(count)
            ]
    return headers, rows


def _cloud(n=12, *, width=4, height=3, intensity_range="u16"):
    rng = np.random.default_rng(904)
    positions = rng.standard_normal((n, 3)).astype(np.float32)
    normals = rng.standard_normal((n, 3)).astype(np.float32)
    colors = rng.integers(0, 256, (n, 3), dtype=np.uint8)
    if intensity_range == "u8":
        intensity = rng.integers(0, 256, n).astype(np.float32)
    elif intensity_range == "u16":
        intensity = rng.integers(0, 65536, n).astype(np.float32)
    else:
        intensity = rng.standard_normal(n).astype(np.float32)
    return _core.point_cloud(
        positions,
        colors=colors,
        normals=normals,
        intensity=intensity,
        intensity_range=intensity_range,
        width=width,
        height=height,
        viewpoint=np.asarray(
            [1.25, -2.5, 3.75, 0.5, 0.5, -0.5, 0.5],
            dtype=np.float64,
        ),
    )


def _assert_cloud_equal(actual, expected):
    assert (
        actual.num_points,
        actual.has_rgb,
        actual.has_rgb16,
        actual.has_normals,
        actual.has_intensity,
        actual.intensity_range,
        actual.width,
        actual.height,
        actual.is_organized,
        actual.viewpoint,
    ) == (
        expected.num_points,
        expected.has_rgb,
        expected.has_rgb16,
        expected.has_normals,
        expected.has_intensity,
        expected.intensity_range,
        expected.width,
        expected.height,
        expected.is_organized,
        expected.viewpoint,
    )
    for name in ("positions", "colors", "normals", "intensities"):
        np.testing.assert_array_equal(
            np.asarray(getattr(actual, name)),
            np.asarray(getattr(expected, name)),
        )


@pytest.mark.parametrize("storage", ["ascii", "binary", "binary_compressed"])
@pytest.mark.parametrize("intensity_range", ["unknown", "u8", "u16"])
def test_writer_roundtrip_and_independent_oracle(storage, intensity_range):
    expected = _cloud(intensity_range=intensity_range)
    encoded = bytes(_core.write_pcd(expected, storage))
    actual = _core.read_pcd(encoded)
    _assert_cloud_equal(actual, expected)

    headers, rows = _oracle(encoded)
    assert headers["FIELDS"] == [
        "x",
        "y",
        "z",
        "normal_x",
        "normal_y",
        "normal_z",
        "rgb",
        "intensity",
    ]
    assert headers["WIDTH"] == ["4"] and headers["HEIGHT"] == ["3"]
    assert tuple(map(float, headers["VIEWPOINT"])) == expected.viewpoint
    values = np.asarray(rows)
    np.testing.assert_array_equal(values[:, :3].astype(np.float32), expected.positions)
    np.testing.assert_array_equal(values[:, 3:6].astype(np.float32), expected.normals)
    packed = values[:, 6].astype(np.uint32)
    colors = np.column_stack(
        ((packed >> 16) & 255, (packed >> 8) & 255, packed & 255)
    ).astype(np.uint8)
    np.testing.assert_array_equal(colors, expected.colors)
    np.testing.assert_array_equal(
        values[:, 7].astype(np.float32), expected.intensities
    )


@pytest.mark.parametrize("storage", ["ascii", "binary", "binary_compressed"])
def test_writer_preserves_float32_special_values(storage):
    bits = np.asarray(
        [0, 0x80000000, 0x7F800000, 0xFF800000, 0x7FC12345, 0xFFC54321],
        dtype=np.uint32,
    )
    positions = np.resize(bits.view(np.float32), (6, 3)).copy()
    decoded = _core.read_pcd(
        _core.write_pcd(_core.point_cloud(positions), storage)
    )
    actual = np.asarray(decoded.positions)
    if storage != "ascii":
        np.testing.assert_array_equal(
            actual.view(np.uint32), positions.view(np.uint32)
        )
    else:
        non_nan = ~np.isnan(positions)
        np.testing.assert_array_equal(
            actual.view(np.uint32)[non_nan],
            positions.view(np.uint32)[non_nan],
        )
        assert np.array_equal(np.isnan(actual), np.isnan(positions))
        assert np.array_equal(np.signbit(actual), np.signbit(positions))


@pytest.mark.parametrize(
    ("kind", "size", "values"),
    [
        ("I", 1, (-7, 8)),
        ("U", 1, (7, 8)),
        ("I", 2, (-700, 800)),
        ("U", 2, (700, 800)),
        ("I", 4, (-70000, 80000)),
        ("U", 4, (70000, 80000)),
        ("I", 8, (-70000, 80000)),
        ("U", 8, (70000, 80000)),
        ("F", 4, (-1.25, 2.5)),
        ("F", 8, (-1.25, 2.5)),
    ],
)
@pytest.mark.parametrize("storage", ["ascii", "binary", "binary_compressed"])
def test_reader_accepts_all_standard_scalar_types(kind, size, values, storage):
    fields = [("z", 4, "F"), ("x", size, kind), ("y", 4, "F")]
    rows = [(3.0, values[0], 2.0), (6.0, values[1], 5.0)]
    decoded = _core.read_pcd(_make_pcd(storage, fields, rows))
    np.testing.assert_array_equal(
        decoded.positions,
        np.asarray(
            [[values[0], 2, 3], [values[1], 5, 6]],
            dtype=np.float32,
        ),
    )


@pytest.mark.parametrize("storage", ["ascii", "binary", "binary_compressed"])
def test_reordered_fields_float_packed_rgb_and_intensity_tags(storage):
    packed_bits = 0x00010203
    packed_float = struct.unpack("<f", struct.pack("<I", packed_bits))[0]
    fields = [
        ("intensity", 1, "U"),
        ("normal_z", 8, "F"),
        ("rgb", 4, "F"),
        ("z", 2, "I"),
        ("normal_x", 4, "F"),
        ("x", 8, "F"),
        ("normal_y", 4, "F"),
        ("y", 4, "U"),
    ]
    rows = [(255, 0.3, packed_float, 3, 0.1, 1.5, 0.2, 2)]
    decoded = _core.read_pcd(_make_pcd(storage, fields, rows))
    np.testing.assert_array_equal(decoded.positions, [[1.5, 2, 3]])
    np.testing.assert_allclose(decoded.normals, [[0.1, 0.2, 0.3]])
    np.testing.assert_array_equal(decoded.colors, [[1, 2, 3]])
    np.testing.assert_array_equal(decoded.intensities, [255])
    assert decoded.intensity_range == "u8"


def test_point_cloud_organization_and_viewpoint_factory_contract():
    positions = np.zeros((12, 3), dtype=np.float32)
    default = _core.point_cloud(positions)
    assert (default.width, default.height, default.is_organized) == (12, 1, False)
    assert default.viewpoint == (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)

    organized = _core.point_cloud(
        positions,
        width=4,
        height=3,
        viewpoint=np.arange(7, dtype=np.float64),
    )
    assert (organized.width, organized.height, organized.is_organized) == (4, 3, True)
    assert organized.viewpoint == tuple(map(float, range(7)))

    for kwargs in (
        {"width": 4},
        {"height": 3},
        {"width": 5, "height": 3},
        {"width": 12, "height": 0},
        {"width": 0, "height": 2},
        {"viewpoint": np.zeros(6, dtype=np.float64)},
        {
            "viewpoint": np.asarray(
                [0, 0, 0, 1, 0, 0, np.inf], dtype=np.float64
            )
        },
    ):
        with pytest.raises((TypeError, ValueError)):
            _core.point_cloud(positions, **kwargs)


def test_open3d_bidirectional_parity_all_storage_modes(tmp_path):
    o3d = pytest.importorskip("open3d")
    expected = _cloud(intensity_range="unknown")
    for storage in ("ascii", "binary", "binary_compressed"):
        path = tmp_path / f"sceneio-{storage}.pcd"
        path.write_bytes(bytes(_core.write_pcd(expected, storage)))
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
    for ascii_mode, compressed in ((True, False), (False, False), (False, True)):
        path = tmp_path / f"open3d-{ascii_mode}-{compressed}.pcd"
        assert o3d.io.write_point_cloud(
            str(path),
            oracle,
            write_ascii=ascii_mode,
            compressed=compressed,
        )
        actual = _core.read_pcd(path.read_bytes())
        np.testing.assert_allclose(actual.positions, expected.positions)
        np.testing.assert_allclose(actual.normals, expected.normals)
        np.testing.assert_allclose(actual.colors, expected.colors, atol=1)


def test_binary_point_ranges_equal_full_slice_and_other_modes_refuse():
    expected = _cloud()
    encoded = bytes(_core.write_pcd(expected, "binary"))
    selected = _core.read_pcd_points(encoded, 3, 10)
    assert (
        selected.num_points,
        selected.width,
        selected.height,
        selected.is_organized,
        selected.viewpoint,
    ) == (7, 7, 1, False, expected.viewpoint)
    for name in ("positions", "colors", "normals", "intensities"):
        np.testing.assert_array_equal(
            np.asarray(getattr(selected, name)),
            np.asarray(getattr(expected, name))[3:10],
        )
    for storage in ("ascii", "binary_compressed"):
        with pytest.raises(ValueError, match="uncompressed binary"):
            _core.read_pcd_points(
                _core.write_pcd(expected, storage), 3, 10
            )
    for bounds in ((0, 0), (3, 2), (0, 13)):
        with pytest.raises(ValueError):
            _core.read_pcd_points(encoded, *bounds)


def test_public_detection_inspection_dispatch_and_partial(tmp_path):
    expected = _cloud()
    path = tmp_path / "points.pcd"
    sceneio.write(expected, path)
    assert sceneio.detect(path) == "pcd"
    actual = sceneio.read(path)
    _assert_cloud_equal(actual, expected)
    selected = sceneio.read_partial(path, points=(2, 9))
    assert selected.num_points == 7

    info = sceneio.inspect(path)
    assert (
        info.format,
        info.datatype,
        info.shape,
        info.dtype,
        info.count,
    ) == ("pcd", "point_cloud", (12, 3), "float32", 12)
    assert info.metadata == {
        "storage": "binary",
        "fields": (
            "x",
            "y",
            "z",
            "normal_x",
            "normal_y",
            "normal_z",
            "rgb",
            "intensity",
        ),
        "sizes": (4, 4, 4, 4, 4, 4, 4, 2),
        "types": ("F", "F", "F", "F", "F", "F", "U", "U"),
        "counts": (1, 1, 1, 1, 1, 1, 1, 1),
        "width": 4,
        "height": 3,
        "organized": True,
        "viewpoint": expected.viewpoint,
        "has_normals": True,
        "has_color": True,
        "has_intensity": True,
        "intensity_range": "u16",
        "point_stride": 30,
        "compressed_size": 0,
    }

    extensionless = tmp_path / "points"
    extensionless.write_bytes(path.read_bytes())
    assert sceneio.detect(extensionless) == "pcd"


def test_inspection_is_header_only_for_large_sparse_binary(tmp_path):
    count = 9_000_000
    header = _make_pcd(
        "binary",
        [("x", 4, "F"), ("y", 4, "F"), ("z", 4, "F")],
        [],
        width=0,
    )
    header = header.replace(b"WIDTH 0\n", f"WIDTH {count}\n".encode()).replace(
        b"POINTS 0\n", f"POINTS {count}\n".encode()
    )
    path = tmp_path / "sparse-large.pcd"
    with path.open("wb") as stream:
        stream.write(header)
        stream.truncate(len(header) + count * 12)
    tracemalloc.start()
    info = sceneio.inspect(path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert (info.count, info.byte_size) == (count, len(header) + count * 12)
    assert peak < 256 * 1024


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ((b"VERSION .7\n", b"VERSION .6\n"), "VERSION"),
        ((b"FIELDS x y z\n", b"FIELD x y z\n"), "expected FIELDS"),
        ((b"SIZE 4 4 4\n", b"SIZE 4 4\n"), "lengths differ"),
        ((b"TYPE F F F\n", b"TYPE F Q F\n"), "unsupported TYPE"),
        ((b"COUNT 1 1 1\n", b"COUNT 1 0 1\n"), "positive"),
        ((b"WIDTH 1\n", b"WIDTH 2\n"), r"WIDTH\*HEIGHT"),
        ((b"VIEWPOINT 0 0 0 1 0 0 0\n", b"VIEWPOINT 0 0 nan 1 0 0 0\n"), "VIEWPOINT"),
        ((b"DATA binary\n", b"DATA other\n"), "unsupported DATA"),
    ],
)
def test_malformed_headers_raise(replacement, message):
    payload = _make_pcd(
        "binary",
        [("x", 4, "F"), ("y", 4, "F"), ("z", 4, "F")],
        [(1, 2, 3)],
    )
    payload = payload.replace(*replacement)
    with pytest.raises(ValueError, match=message):
        _core.read_pcd(payload)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ([("x", 4, "F"), ("y", 4, "F")], "missing field"),
        (
            [("x", 4, "F"), ("y", 4, "F"), ("z", 4, "F"), ("normal_x", 4, "F")],
            "normals require",
        ),
        (
            [("x", 4, "F"), ("y", 4, "F"), ("z", 4, "F"), ("temperature", 4, "F")],
            "unsupported field",
        ),
        (
            [("x", 4, "F"), ("y", 4, "F"), ("z", 4, "F"), ("rgb", 2, "U")],
            "rgb must be",
        ),
    ],
)
def test_unrepresentable_schemas_raise(fields, message):
    with pytest.raises(ValueError, match=message):
        _core.read_pcd(_make_pcd("binary", fields, [(0,) * len(fields)]))


def test_count_greater_than_one_and_duplicate_fields_raise():
    payload = _make_pcd(
        "binary",
        [("x", 4, "F"), ("y", 4, "F"), ("z", 4, "F")],
        [(1, 2, 3)],
    )
    with pytest.raises(ValueError, match="COUNT 1"):
        _core.read_pcd(payload.replace(b"COUNT 1 1 1\n", b"COUNT 1 2 1\n"))
    with pytest.raises(ValueError, match="unique"):
        _core.read_pcd(payload.replace(b"FIELDS x y z\n", b"FIELDS x x z\n"))


def test_columns_alias_is_accepted_as_pcd_compatibility_spelling():
    payload = _make_pcd(
        "binary",
        [("x", 4, "F"), ("y", 4, "F"), ("z", 4, "F")],
        [(1, 2, 3)],
    ).replace(b"FIELDS x y z\n", b"COLUMNS x y z\n")
    np.testing.assert_array_equal(_core.read_pcd(payload).positions, [[1, 2, 3]])


def test_truncation_trailing_ascii_and_float64_overflow_raise():
    fields = [("x", 4, "F"), ("y", 4, "F"), ("z", 4, "F")]
    binary = _make_pcd("binary", fields, [(1, 2, 3)])
    with pytest.raises(ValueError, match="truncated"):
        _core.read_pcd(binary[:-1])
    with pytest.raises(ValueError, match="trailing"):
        _core.read_pcd(binary + b"x")
    ascii_data = _make_pcd("ascii", fields, [(1, 2, 3)])
    with pytest.raises(ValueError, match=r"truncated|count exceeds payload"):
        _core.read_pcd(ascii_data.rsplit(b" ", 1)[0])
    with pytest.raises(ValueError, match="trailing"):
        _core.read_pcd(ascii_data + b" 4")
    overflow = _make_pcd(
        "binary",
        [("x", 8, "F"), ("y", 4, "F"), ("z", 4, "F")],
        [(1e300, 2, 3)],
    )
    with pytest.raises(ValueError, match="overflows float32"):
        _core.read_pcd(overflow)


def test_declared_count_bombs_raise_before_record_allocation():
    payload = _make_pcd(
        "binary",
        [("x", 4, "F"), ("y", 4, "F"), ("z", 4, "F")],
        [],
        width=0,
    )
    payload = payload.replace(b"WIDTH 0\n", b"WIDTH 4294967295\n").replace(
        b"POINTS 0\n", b"POINTS 4294967295\n"
    )
    with pytest.raises(ValueError, match=r"truncated|extent"):
        _core.read_pcd(payload)

    ascii_payload = payload.replace(b"DATA binary\n", b"DATA ascii\n")
    with pytest.raises(ValueError, match="count exceeds payload"):
        _core.read_pcd(ascii_payload)


def test_header_limit_and_unterminated_header_are_bounded():
    payload = (
        b"#"
        + b"x" * (1024 * 1024)
        + b"\nVERSION .7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\n"
        b"COUNT 1 1 1\nWIDTH 0\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\n"
        b"POINTS 0\nDATA binary\n"
    )
    with pytest.raises(ValueError, match="header exceeds"):
        _core.read_pcd(payload)
    with pytest.raises(ValueError, match=r"missing|unterminated"):
        _core.read_pcd(b"VERSION .7")


def test_inspection_rejects_malformed_payload_extents(tmp_path):
    fields = [("x", 4, "F"), ("y", 4, "F"), ("z", 4, "F")]
    binary = _make_pcd("binary", fields, [(1, 2, 3)])
    compressed = _make_pcd("binary_compressed", fields, [(1, 2, 3)])
    header_end = compressed.index(b"DATA binary_compressed\n") + len(
        b"DATA binary_compressed\n"
    )
    compressed_body = bytearray(compressed[header_end:])
    struct.pack_into("<I", compressed_body, 4, 13)
    cases = (
        binary[:-1],
        binary + b"x",
        _make_pcd("ascii", fields, [(1, 2, 3)]).rsplit(b" ", 1)[0],
        compressed[:header_end] + compressed_body,
        compressed[:-1],
        compressed + b"x",
    )
    for index, payload in enumerate(cases):
        path = tmp_path / f"bad-{index}.pcd"
        path.write_bytes(payload)
        with pytest.raises(sceneio.FormatError):
            sceneio.inspect(path)


def test_malformed_compressed_size_and_lzf_streams_raise_before_decode():
    fields = [("x", 4, "F"), ("y", 4, "F"), ("z", 4, "F")]
    valid = _make_pcd("binary_compressed", fields, [(1, 2, 3)])
    header_end = valid.index(b"DATA binary_compressed\n") + len(
        b"DATA binary_compressed\n"
    )
    body = valid[header_end:]
    compressed_size, raw_size = struct.unpack_from("<II", body)
    assert compressed_size > 0 and raw_size == 12
    cases = [
        valid[:header_end] + b"\0" * 7,
        valid[:header_end] + struct.pack("<II", compressed_size, 13) + body[8:],
        valid[:-1],
        valid + b"x",
        valid[:header_end] + struct.pack("<II", 2, 12) + b"\xe0\x00",
        valid[:header_end] + struct.pack("<II", 1, 12) + b"\x1f",
    ]
    for payload in cases:
        with pytest.raises(ValueError):
            _core.read_pcd(payload)


def test_valid_overlapping_lzf_back_reference_and_repeated_writer_stream():
    fields = [("x", 4, "F"), ("y", 4, "F"), ("z", 4, "F")]
    # One literal zero followed by an 11-byte, distance-one overlapping match:
    # encoded length 9 => extended control 0xe0, extra 2, low distance 0.
    payload = _make_pcd(
        "binary_compressed",
        fields,
        [(0, 0, 0)],
        compressed_payload=b"\x00\x00\xe0\x02\x00",
    )
    np.testing.assert_array_equal(_core.read_pcd(payload).positions, [[0, 0, 0]])

    repeated = _core.point_cloud(np.zeros((1000, 3), dtype=np.float32))
    encoded = bytes(_core.write_pcd(repeated, "binary_compressed"))
    header_end = encoded.index(b"DATA binary_compressed\n") + len(
        b"DATA binary_compressed\n"
    )
    compressed_size, raw_size = struct.unpack_from("<II", encoded, header_end)
    assert compressed_size < raw_size / 10
    _, rows = _oracle(encoded)
    assert np.array_equal(np.asarray(rows, dtype=np.float32), repeated.positions)


def test_empty_cloud_all_modes():
    empty = _core.point_cloud(
        np.empty((0, 3), dtype=np.float32),
        width=0,
        height=1,
    )
    for storage in ("ascii", "binary", "binary_compressed"):
        decoded = _core.read_pcd(_core.write_pcd(empty, storage))
        assert (decoded.num_points, decoded.width, decoded.height) == (0, 0, 1)


def test_writer_refuses_unrepresentable_metadata_and_values():
    positions = np.zeros((2, 3), dtype=np.float32)
    bad = [
        _core.point_cloud(
            positions,
            colors16=np.zeros((2, 3), dtype=np.uint16),
        ),
        _core.point_cloud(positions, coordinate_frame="enu"),
        _core.point_cloud(positions, scale_to_meters=0.01),
        _core.point_cloud(
            positions,
            origin=np.asarray([1, 0, 0], dtype=np.float64),
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
            _core.write_pcd(cloud)
    with pytest.raises(ValueError, match="encoding must be"):
        _core.write_pcd(_core.point_cloud(positions), "other")


def test_other_point_writers_refuse_pcd_only_metadata():
    positions = np.zeros((6, 3), dtype=np.float32)
    records = (
        _core.point_cloud(positions, width=3, height=2),
        _core.point_cloud(
            positions,
            viewpoint=np.asarray([1, 0, 0, 1, 0, 0, 0], dtype=np.float64),
        ),
    )
    for cloud in records:
        for writer in (
            _core.write_xyz,
            _core.write_pts,
            _core.write_ply,
            _core.write_las,
        ):
            with pytest.raises(ValueError, match=r"organized|viewpoint"):
                writer(cloud)


def test_mmap_bytes_lifetime_mutation_isolation_and_memory(tmp_path):
    rng = np.random.default_rng(905)
    positions = rng.standard_normal((600_000, 3)).astype(np.float32)
    cloud = _core.point_cloud(positions)
    payload = bytes(_core.write_pcd(cloud))
    path = tmp_path / "large.pcd"
    path.write_bytes(payload)
    expected = _core.read_pcd(payload)
    with (
        path.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
    ):
        tracemalloc.start()
        actual = _core.read_pcd(mapped)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    gc.collect()
    np.testing.assert_array_equal(actual.positions, expected.positions)
    assert peak < len(payload) + 1024 * 1024

    copied = np.asarray(actual.positions).copy()
    path.write_bytes(bytes(_core.write_pcd(_core.point_cloud(-positions))))
    np.testing.assert_array_equal(actual.positions, copied)


def test_file_sink_is_identical_and_guard_does_not_truncate(tmp_path):
    cloud = _cloud()
    expected = bytes(_core.write_pcd(cloud))
    path = tmp_path / "points.pcd"
    sceneio.write(cloud, path)
    assert path.read_bytes() == expected
    _core._write_to_file(_core.write_pcd, cloud, path)
    assert path.read_bytes() == expected

    path.write_bytes(b"keep")
    bad = _core.point_cloud(
        np.zeros((1, 3), dtype=np.float32), coordinate_frame="enu"
    )
    with pytest.raises(ValueError):
        _core._write_to_file(_core.write_pcd, bad, path)
    assert path.read_bytes() == b"keep"


def test_binary_file_sink_streams_without_output_sized_python_allocation(
    tmp_path,
):
    positions = np.random.default_rng(906).standard_normal(
        (300_000, 3)
    ).astype(np.float32)
    cloud = _core.point_cloud(positions)
    expected = bytes(_core.write_pcd(cloud))
    path = tmp_path / "streamed.pcd"

    tracemalloc.start()
    try:
        _core._write_to_file(_core.write_pcd, cloud, path)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert path.read_bytes() == expected
    assert peak < len(expected) / 8
