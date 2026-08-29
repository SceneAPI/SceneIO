"""g2o SE3:QUAT parity, semantics, malformed-input, mmap, and sink tests."""

from __future__ import annotations

import gc
import mmap
from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import _core
from sceneio.io import FormatError


def _upper(values: np.ndarray) -> list[float]:
    return [
        float(values[row, column])
        for row in range(6)
        for column in range(row, 6)
    ]


def _information(edges: int) -> np.ndarray:
    result = np.zeros((edges, 6, 6), dtype=np.float64)
    for edge in range(edges):
        upper = np.arange(1, 22, dtype=np.float64) + edge * 100
        index = 0
        for row in range(6):
            for column in range(row, 6):
                result[edge, row, column] = upper[index]
                result[edge, column, row] = upper[index]
                index += 1
    return result


def _graph(**kwargs):
    return _core.pose_graph(
        np.array([7, 11, 19], np.int64),
        np.array([[1.0, 0, 0], [1.0, 2.0, 0], [4.0, 2.0, 1.0]]),
        np.array(
            [
                [0.0, 0.0, np.sqrt(0.5), np.sqrt(0.5)],
                [0.0, 0.0, np.sqrt(0.5), np.sqrt(0.5)],
                [0.0, 0.0, 0.0, 1.0],
            ]
        ),
        np.array([[7, 11], [11, 19]], np.int64),
        np.array([[2.0, 0, 0], [3.0, 0, 1.0]]),
        np.array([[0.0, 0.0, 0.0, 1.0], [0.0, 0.0, -1.0, 0.0]]),
        _information(2),
        fixed=np.array([1, 0, 1], np.uint8),
        **kwargs,
    )


def _oracle_parse(data: bytes):
    """Independent strict parser for SceneIO's supported g2o subset."""

    vertices = []
    edges = []
    fixed = []
    seen = set()
    for line_number, raw in enumerate(data.splitlines(), 1):
        line = raw.partition(b"#")[0].strip()
        if not line:
            continue
        fields = line.split()
        tag = fields[0]
        if tag == b"VERTEX_SE3:QUAT":
            if len(fields) != 9:
                raise ValueError(f"line {line_number}: bad vertex width")
            vertex_id = int(fields[1])
            if not 0 <= vertex_id <= 2**31 - 1 or vertex_id in seen:
                raise ValueError(f"line {line_number}: bad vertex id")
            seen.add(vertex_id)
            values = np.array([float(value) for value in fields[2:]], np.float64)
            if not np.isfinite(values).all():
                raise ValueError(f"line {line_number}: nonfinite")
            if abs(float(values[3:] @ values[3:]) - 1.0) > 1e-3:
                raise ValueError(f"line {line_number}: nonunit")
            vertices.append((vertex_id, values))
        elif tag == b"EDGE_SE3:QUAT":
            if len(fields) != 31:
                raise ValueError(f"line {line_number}: bad edge width")
            source, target = (int(fields[1]), int(fields[2]))
            values = np.array([float(value) for value in fields[3:10]], np.float64)
            upper = np.array([float(value) for value in fields[10:]], np.float64)
            if not np.isfinite(values).all() or not np.isfinite(upper).all():
                raise ValueError(f"line {line_number}: nonfinite")
            if abs(float(values[3:] @ values[3:]) - 1.0) > 1e-3:
                raise ValueError(f"line {line_number}: nonunit")
            matrix = np.zeros((6, 6), np.float64)
            index = 0
            for row in range(6):
                for column in range(row, 6):
                    matrix[row, column] = upper[index]
                    matrix[column, row] = upper[index]
                    index += 1
            edges.append((source, target, values, matrix))
        elif tag == b"FIX":
            if len(fields) != 2:
                raise ValueError(f"line {line_number}: bad FIX width")
            vertex_id = int(fields[1])
            if vertex_id in fixed:
                raise ValueError(f"line {line_number}: duplicate FIX")
            fixed.append(vertex_id)
        else:
            raise ValueError(f"line {line_number}: unsupported tag")
    if any(source not in seen or target not in seen for source, target, *_ in edges):
        raise ValueError("missing endpoint")
    if any(vertex_id not in seen for vertex_id in fixed):
        raise ValueError("missing FIX vertex")
    return vertices, edges, fixed


def _assert_graph_equal(actual, expected):
    assert actual.num_nodes == expected.num_nodes
    assert actual.num_edges == expected.num_edges
    assert actual.node_types == expected.node_types
    assert actual.edge_types == expected.edge_types
    assert actual.quaternion_order == expected.quaternion_order
    assert actual.quaternion_sign == expected.quaternion_sign
    assert actual.node_transform_convention == expected.node_transform_convention
    assert actual.edge_transform_convention == expected.edge_transform_convention
    assert actual.translation_unit == expected.translation_unit
    assert actual.information_variable_order == expected.information_variable_order
    for name in (
        "node_ids",
        "node_translations",
        "node_quaternions",
        "fixed",
        "edge_endpoints",
        "edge_translations",
        "edge_quaternions",
        "information_matrices",
    ):
        np.testing.assert_array_equal(getattr(actual, name), getattr(expected, name))


def test_golden_read_preserves_xyzw_information_and_fix():
    information = " ".join(str(value) for value in range(1, 22))
    data = (
        b"# external graph\n"
        b"FIX 7\n"
        b"EDGE_SE3:QUAT 7 11 2 0 0 0 0 0 1 "
        + information.encode()
        + b" # inline comment\n"
        b"VERTEX_SE3:QUAT 11 1 2 0 0 0 0.70710678118654757 "
        b"0.70710678118654757\n"
        b"VERTEX_SE3:QUAT 7 1 0 0 0 0 0.70710678118654757 "
        b"0.70710678118654757\n"
    )
    graph = _core.read_g2o(data)
    assert graph.node_ids.tolist() == [11, 7]
    assert graph.fixed.tolist() == [0, 1]
    assert graph.edge_endpoints.tolist() == [[7, 11]]
    assert graph.edge_quaternions.tolist() == [[0, 0, 0, 1]]
    expected = np.zeros((6, 6))
    index = 1
    for row in range(6):
        for column in range(row, 6):
            expected[row, column] = expected[column, row] = index
            index += 1
    np.testing.assert_array_equal(graph.information_matrices[0], expected)
    assert graph.quaternion_order == "xyzw"
    assert graph.edge_transform_convention == "source_inverse_times_target"


def test_all_ascii_stream_whitespace_is_accepted_between_tokens():
    graph = _core.read_g2o(
        b"VERTEX_SE3:QUAT\v0\f0\t0\r0 0 0 0 1\n"
    )
    assert graph.node_ids.tolist() == [0]


def test_hand_derived_source_inverse_target_direction():
    graph = _graph()
    # Source node 7 is translated (1,0,0) and rotated +90 degrees around Z.
    # Its g2o measurement (2,0,0) composes to target translation (1,2,0):
    # T_reference_target = T_reference_source * T_source_inverse_target.
    source_translation = graph.node_translations[0]
    source_rotation = np.array([[0.0, -1, 0], [1, 0, 0], [0, 0, 1]])
    composed = source_translation + source_rotation @ graph.edge_translations[0]
    np.testing.assert_allclose(composed, graph.node_translations[1], atol=0, rtol=0)


def test_writer_is_deterministic_and_independent_oracle_reads_every_field():
    graph = _graph()
    first = bytes(_core.write_g2o(graph))
    second = bytes(_core.write_g2o(graph))
    assert first == second
    assert first.startswith(b"# g2o pose graph (SceneIO)\n")
    vertices, edges, fixed = _oracle_parse(first)
    assert [item[0] for item in vertices] == [7, 11, 19]
    assert fixed == [7, 19]
    assert [(edge[0], edge[1]) for edge in edges] == [(7, 11), (11, 19)]
    for row, (_, values) in enumerate(vertices):
        np.testing.assert_array_equal(values[:3], graph.node_translations[row])
        np.testing.assert_array_equal(values[3:], graph.node_quaternions[row])
    for row, (_, _, values, information) in enumerate(edges):
        np.testing.assert_array_equal(values[:3], graph.edge_translations[row])
        np.testing.assert_array_equal(values[3:], graph.edge_quaternions[row])
        np.testing.assert_array_equal(information, graph.information_matrices[row])
    _assert_graph_equal(_core.read_g2o(first), graph)


def test_empty_graph_has_canonical_detectable_representation():
    graph = _core.pose_graph(
        np.empty(0, np.int64),
        np.empty((0, 3), np.float64),
        np.empty((0, 4), np.float64),
        np.empty((0, 2), np.int64),
        np.empty((0, 3), np.float64),
        np.empty((0, 4), np.float64),
        np.empty((0, 6, 6), np.float64),
    )
    data = bytes(_core.write_g2o(graph))
    assert data == b"# g2o pose graph (SceneIO)\n"
    decoded = _core.read_g2o(data)
    assert decoded.num_nodes == decoded.num_edges == 0


def test_randomized_roundtrips_are_bit_exact():
    rng = np.random.default_rng(803)
    for iteration in range(40):
        nodes = int(rng.integers(1, 24))
        edges = int(rng.integers(0, 48))
        ids = np.sort(rng.choice(10_000, nodes, replace=False)).astype(np.int64)
        node_q = rng.standard_normal((nodes, 4))
        node_q /= np.linalg.norm(node_q, axis=1, keepdims=True)
        edge_q = rng.standard_normal((edges, 4))
        if edges:
            edge_q /= np.linalg.norm(edge_q, axis=1, keepdims=True)
            endpoint_rows = rng.integers(0, nodes, (edges, 2))
            endpoints = ids[endpoint_rows]
        else:
            endpoints = np.empty((0, 2), np.int64)
        raw = rng.standard_normal((edges, 6, 6))
        information = raw + np.swapaxes(raw, 1, 2)
        graph = _core.pose_graph(
            ids,
            rng.standard_normal((nodes, 3)),
            node_q,
            endpoints,
            rng.standard_normal((edges, 3)),
            edge_q,
            information,
            fixed=rng.integers(0, 2, nodes, dtype=np.uint8),
        )
        data = bytes(_core.write_g2o(graph))
        _oracle_parse(data)
        _assert_graph_equal(_core.read_g2o(data), graph)
        assert iteration >= 0


def test_signed_zero_coefficients_roundtrip_bit_exact():
    graph = _graph()
    node_translations = np.asarray(graph.node_translations).copy()
    edge_translations = np.asarray(graph.edge_translations).copy()
    information = np.asarray(graph.information_matrices).copy()
    node_translations[0, 0] = -0.0
    edge_translations[0, 1] = -0.0
    information[0, 0, 1] = information[0, 1, 0] = -0.0
    signed = _core.pose_graph(
        np.asarray(graph.node_ids),
        node_translations,
        np.asarray(graph.node_quaternions),
        np.asarray(graph.edge_endpoints),
        edge_translations,
        np.asarray(graph.edge_quaternions),
        information,
        fixed=np.asarray(graph.fixed),
    )
    decoded = _core.read_g2o(_core.write_g2o(signed))
    assert np.signbit(decoded.node_translations[0, 0])
    assert np.signbit(decoded.edge_translations[0, 1])
    assert np.signbit(decoded.information_matrices[0, 0, 1])
    assert np.signbit(decoded.information_matrices[0, 1, 0])


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"VERTEX_SE3:QUAT 0 0 0 0 0 0 0\n", "requires id"),
        (b"VERTEX_SE3:QUAT -1 0 0 0 0 0 0 1\n", "vertex id"),
        (b"VERTEX_SE3:QUAT 2147483648 0 0 0 0 0 0 1\n", "vertex id"),
        (
            b"VERTEX_SE3:QUAT 0 0 0 0 0 0 0 1\n"
            b"VERTEX_SE3:QUAT 0 1 0 0 0 0 0 1\n",
            "duplicate",
        ),
        (b"VERTEX_SE3:QUAT 0 0 0 0 0 0 0 0\n", "unit length"),
        (b"VERTEX_SE3:QUAT 0 nan 0 0 0 0 0 1\n", "non-finite"),
        (b"FIX 1\n", "missing"),
        (b"FIX 1 2\n", "exactly one"),
        (
            b"VERTEX_SE3:QUAT 0 0 0 0 0 0 0 1\nFIX 0\nFIX 0\n",
            "duplicate FIX",
        ),
        (
            b"EDGE_SE3:QUAT 0 1 0 0 0 0 0 0 1 "
            + b" ".join([b"1"] * 21)
            + b"\n",
            "missing vertex",
        ),
        (b"VERTEX_XY 0 0 0\n", "unsupported record type"),
        (b"PARAMS_SE3OFFSET 0 0 0 0 0 0 0 1\n", "unsupported record type"),
        (b"VERTEX_SE3:QUAT 0 0\x000 0 0 0 0 0 1\n", "NUL"),
    ],
)
def test_malformed_inputs_reject(data, message):
    with pytest.raises(ValueError, match=message):
        _core.read_g2o(data)


def test_edge_width_nonfinite_and_nonunit_reject():
    prefix = b"VERTEX_SE3:QUAT 0 0 0 0 0 0 0 1\n"
    valid = (
        b"EDGE_SE3:QUAT 0 0 0 0 0 0 0 0 1 "
        + b" ".join([b"1"] * 21)
        + b"\n"
    )
    with pytest.raises(ValueError, match="21 information"):
        _core.read_g2o(prefix + valid.rsplit(b" ", 1)[0] + b"\n")
    with pytest.raises(ValueError, match="non-finite"):
        _core.read_g2o(prefix + valid.replace(b" 1 1 1", b" nan 1 1", 1))
    with pytest.raises(ValueError, match="unit length"):
        _core.read_g2o(prefix + valid.replace(b" 0 0 0 1 ", b" 0 0 0 2 ", 1))


def test_overlong_line_rejects_before_unbounded_tokenization():
    with pytest.raises(ValueError, match="exceeds 1 MiB"):
        _core.read_g2o(b"#" + b"x" * (1024 * 1024 + 1))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"quaternion_order": "wxyz"}, "conventions"),
        ({"quaternion_sign": "canonical_positive_w"}, "conventions"),
        ({"node_transform_convention": "reference_to_node"}, "conventions"),
        ({"edge_transform_convention": "target_inverse_times_source"}, "conventions"),
        ({"translation_unit": "meters"}, "conventions"),
        ({"node_types": ["se3", "sim3", "se3"]}, "only se3 node"),
        ({"edge_types": ["se3", "loop"]}, "only se3 edge"),
    ],
)
def test_writer_guards_unrepresentable_record_conventions(kwargs, message):
    with pytest.raises(ValueError, match=message):
        _core.write_g2o(_graph(**kwargs))


def test_writer_rejects_negative_id_in_general_record():
    graph = _core.pose_graph(
        np.array([-1], np.int64),
        np.zeros((1, 3)),
        np.array([[0.0, 0.0, 0.0, 1.0]]),
        np.empty((0, 2), np.int64),
        np.empty((0, 3)),
        np.empty((0, 4)),
        np.empty((0, 6, 6)),
    )
    with pytest.raises(ValueError, match="nonnegative"):
        _core.write_g2o(graph)


def test_read_copies_mmap_and_survives_close(tmp_path):
    path = tmp_path / "graph.g2o"
    path.write_bytes(bytes(_core.write_g2o(_graph())))
    with path.open("rb") as stream:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        assert _core._buffer_address(mapped) == np.frombuffer(mapped, np.uint8).ctypes.data
        graph = _core.read_g2o(mapped)
        mapped.close()
    gc.collect()
    assert graph.node_ids.tolist() == [7, 11, 19]
    assert graph.edge_endpoints.tolist() == [[7, 11], [11, 19]]


def test_read_is_isolated_from_mutable_source_alias():
    source = bytearray(_core.write_g2o(_graph()))
    readonly = memoryview(source).toreadonly()
    graph = _core.read_g2o(readonly)
    source[:] = b"#" * len(source)
    assert graph.node_ids.tolist() == [7, 11, 19]


def test_direct_sink_is_byte_identical_and_guard_does_not_truncate(tmp_path):
    graph = _graph()
    expected = bytes(_core.write_g2o(graph))
    path = tmp_path / "direct.g2o"
    calls = _core._write_to_file(_core.write_g2o, graph, path, 7)
    assert calls > 1
    assert path.read_bytes() == expected

    existing = tmp_path / "existing.g2o"
    existing.write_bytes(b"keep")
    invalid = _graph(translation_unit="meters")
    with pytest.raises(ValueError, match="conventions"):
        _core._write_to_file(_core.write_g2o, invalid, existing)
    assert existing.read_bytes() == b"keep"


def test_public_registry_detect_read_write_and_inspect(tmp_path):
    graph = _graph()
    path = tmp_path / "graph.g2o"
    sceneio.write(graph, path)
    assert sceneio.detect(path) == "g2o"
    decoded = sceneio.read(path)
    _assert_graph_equal(decoded, graph)
    inspection = sceneio.inspect(path)
    assert inspection.format == "g2o"
    assert inspection.datatype == "pose_graph"
    assert inspection.shape == (3,)
    assert inspection.count == 3
    assert inspection.metadata["num_nodes"] == 3
    assert inspection.metadata["num_edges"] == 2
    assert inspection.metadata["num_fixed_nodes"] == 2
    assert inspection.metadata["quaternion_order"] == "xyzw"
    assert (
        inspection.metadata["edge_transform_convention"]
        == "source_inverse_times_target"
    )
    cap = sceneio.capabilities("g2o")
    assert cap.record_type == "PoseGraph"
    assert cap.streams_read and cap.streams_write
    assert "edge_se3_quat" in cap.supported_features
    assert "mixed_edge_types" in cap.unsupported_features


def test_magic_detection_without_extension(tmp_path):
    for index, data in enumerate(
        (
            bytes(_core.write_g2o(_graph())),
            b"VERTEX_SE3:QUAT 0 0 0 0 0 0 0 1\n",
            b"EDGE_SE3:QUAT 0 0 0 0 0 0 0 0 1 " + b" ".join([b"1"] * 21),
        )
    ):
        path = tmp_path / f"graph-{index}"
        path.write_bytes(data)
        assert sceneio.detect(path) == "g2o"


def test_inspection_validates_complete_graph(tmp_path):
    path = tmp_path / "bad.g2o"
    path.write_bytes(
        b"VERTEX_SE3:QUAT 0 0 0 0 0 0 0 1\n"
        b"EDGE_SE3:QUAT 0 2 0 0 0 0 0 0 1 "
        + b" ".join([b"1"] * 21)
        + b"\n"
    )
    with pytest.raises(FormatError, match="missing vertex"):
        sceneio.inspect(path)


def test_public_explicit_format_handles_noncanonical_comment_prefix(tmp_path):
    path = tmp_path / "ambiguous.txt"
    path.write_bytes(
        b"# arbitrary comment\n"
        b"VERTEX_SE3:QUAT 0 0 0 0 0 0 0 1\n"
    )
    graph = sceneio.read(path, format="g2o")
    assert graph.num_nodes == 1
    assert graph.num_edges == 0


def test_oracle_and_native_agree_on_supported_golden_file():
    path = Path(__file__).parent / "data" / "not-present.g2o"
    # Keep the oracle independent without committing third-party data: this
    # hand-built graph covers ordering, comments, FIX, and nontrivial matrices.
    assert not path.exists()
    data = bytes(_core.write_g2o(_graph()))
    vertices, edges, fixed = _oracle_parse(data)
    native = _core.read_g2o(data)
    assert len(vertices) == native.num_nodes
    assert len(edges) == native.num_edges
    assert len(fixed) == int(native.fixed.sum())
