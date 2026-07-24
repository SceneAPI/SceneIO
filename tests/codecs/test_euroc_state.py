"""EuRoC ground-truth CSV parity, hardening, mmap, sink, and O5 tests."""

from __future__ import annotations

import csv
import gc
import io
import math
import mmap
import tracemalloc

import numpy as np
import pytest

import sceneio
from sceneio import _core

HEADER = (
    "#timestamp [ns],p_RS_R_x [m],p_RS_R_y [m],p_RS_R_z [m],"
    "q_RS_w [],q_RS_x [],q_RS_y [],q_RS_z [],"
    "v_RS_R_x [m s^-1],v_RS_R_y [m s^-1],v_RS_R_z [m s^-1],"
    "b_w_RS_S_x [rad s^-1],b_w_RS_S_y [rad s^-1],"
    "b_w_RS_S_z [rad s^-1],b_a_RS_S_x [m s^-2],"
    "b_a_RS_S_y [m s^-2],b_a_RS_S_z [m s^-2]"
)


def _arrays(count: int = 5, seed: int = 7):
    rng = np.random.default_rng(seed)
    timestamps = (
        1_403_636_580_000_000_000
        + np.arange(count, dtype=np.int64) * 5_000_000
    )
    positions = rng.normal(size=(count, 3))
    quaternions = rng.normal(size=(count, 4))
    velocities = rng.normal(size=(count, 3))
    gyro_biases = rng.normal(scale=0.01, size=(count, 3))
    accel_biases = rng.normal(scale=0.1, size=(count, 3))
    return (
        timestamps,
        positions,
        quaternions,
        velocities,
        gyro_biases,
        accel_biases,
    )


def _trajectory(count: int = 5, seed: int = 7, **metadata):
    return _core.state_trajectory(*_arrays(count, seed), **metadata)


def _fields(value):
    return (
        np.asarray(value.timestamps_ns),
        np.asarray(value.positions),
        np.asarray(value.quaternions),
        np.asarray(value.velocities),
        np.asarray(value.gyro_biases),
        np.asarray(value.accel_biases),
    )


def _assert_equal(actual, expected):
    assert isinstance(actual, _core.StateTrajectory)
    assert actual.num_states == expected.num_states
    for left, right in zip(_fields(actual), _fields(expected), strict=True):
        np.testing.assert_array_equal(left, right)
        if left.dtype == np.float64:
            np.testing.assert_array_equal(
                left.view(np.uint64), right.view(np.uint64)
            )


def _oracle_decode(data: bytes):
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    assert tuple(field.strip() for field in rows[0]) == tuple(
        field.strip() for field in HEADER.split(",")
    )
    values = [row for row in rows[1:] if row and not row[0].lstrip().startswith("#")]
    timestamps = np.array([int(row[0].strip()) for row in values], np.int64)
    numbers = np.array(
        [[float(field.strip()) for field in row[1:]] for row in values],
        dtype=np.float64,
    ).reshape((-1, 16))
    return timestamps, numbers


def _oracle_accepts(data: bytes) -> bool:
    try:
        rows = csv.reader(io.StringIO(data.decode("utf-8-sig")))
        header = next(rows)
        if tuple(field.strip() for field in header) != tuple(
            field.strip() for field in HEADER.split(",")
        ):
            return False
        previous = -1
        for row in rows:
            if not row or not any(field.strip() for field in row):
                continue
            if row[0].lstrip().startswith("#"):
                continue
            if len(row) != 17 or any(not field.strip() for field in row):
                return False
            token = row[0].strip()
            if not token.isascii() or not token.isdigit():
                return False
            timestamp = int(token)
            if timestamp > np.iinfo(np.int64).max or timestamp <= previous:
                return False
            values = [float(field.strip()) for field in row[1:]]
            if not all(math.isfinite(value) for value in values):
                return False
            if not any(value != 0.0 for value in values[3:7]):
                return False
            previous = timestamp
    except (UnicodeDecodeError, ValueError, StopIteration):
        return False
    return True


def test_golden_fixture_matches_independent_csv_oracle():
    data = (
        HEADER
        + "\n1403636580000000000,1,2,3,1,0,0,0,4,5,6,"
        "0.01,0.02,0.03,0.1,0.2,0.3\n"
    ).encode()
    actual = _core.read_euroc_state(data)
    timestamps, numbers = _oracle_decode(data)
    np.testing.assert_array_equal(actual.timestamps_ns, timestamps)
    np.testing.assert_array_equal(actual.positions, numbers[:, 0:3])
    np.testing.assert_array_equal(actual.quaternions, numbers[:, 3:7])
    np.testing.assert_array_equal(actual.velocities, numbers[:, 7:10])
    np.testing.assert_array_equal(actual.gyro_biases, numbers[:, 10:13])
    np.testing.assert_array_equal(actual.accel_biases, numbers[:, 13:16])


def test_hand_derived_wxyz_sensor_to_reference_convention_pin():
    root_half = math.sqrt(0.5)
    data = (
        HEADER
        + f"\n1,10,20,30,{root_half},0,0,{root_half},"
        "1,2,3,0.01,0.02,0.03,0.1,0.2,0.3\n"
    ).encode()
    trajectory = _core.read_euroc_state(data)
    w, x, y, z = trajectory.quaternions[0]
    rotation = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )
    np.testing.assert_allclose(
        rotation @ [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        atol=1e-15,
    )
    assert (
        trajectory.pose_convention,
        trajectory.position_frame,
        trajectory.velocity_frame,
        trajectory.bias_frame,
    ) == (
        "sensor_to_reference",
        "reference",
        "reference",
        "sensor",
    )


def test_buffer_roundtrip_is_float_bit_exact_and_timestamp_exact():
    expected = _trajectory(37)
    encoded = bytes(_core.write_euroc_state(expected))
    actual = _core.read_euroc_state(encoded)
    _assert_equal(actual, expected)
    oracle_timestamps, oracle_values = _oracle_decode(encoded)
    np.testing.assert_array_equal(oracle_timestamps, expected.timestamps_ns)
    np.testing.assert_array_equal(
        oracle_values,
        np.concatenate(_fields(expected)[1:], axis=1),
    )


def test_negative_zero_sign_is_preserved():
    arrays = list(_arrays(1))
    arrays[1][0, 0] = -0.0
    expected = _core.state_trajectory(*arrays)
    actual = _core.read_euroc_state(_core.write_euroc_state(expected))
    assert np.signbit(actual.positions[0, 0])


def test_extreme_finite_float_and_int64_timestamp_roundtrip():
    arrays = list(_arrays(2))
    arrays[0] = np.array(
        [np.iinfo(np.int64).max - 1, np.iinfo(np.int64).max],
        dtype=np.int64,
    )
    arrays[1][0] = [
        np.finfo(np.float64).max,
        np.finfo(np.float64).tiny,
        np.nextafter(0.0, 1.0),
    ]
    arrays[1][1] = -arrays[1][0]
    expected = _core.state_trajectory(*arrays)
    actual = _core.read_euroc_state(
        _core.write_euroc_state(expected)
    )
    _assert_equal(actual, expected)


def test_header_only_empty_trajectory_roundtrips():
    expected = _trajectory(0)
    encoded = bytes(_core.write_euroc_state(expected))
    assert encoded == (HEADER + "\n").encode()
    _assert_equal(_core.read_euroc_state(encoded), expected)


def test_reader_accepts_bom_crlf_spacing_blank_and_comment_lines():
    spaced_header = ", ".join(HEADER.split(","))
    row = " 10 , 1 , 2 , 3 , 1 , 0 , 0 , 0 , 4 , 5 , 6 , 7 , 8 , 9 , 10 , 11 , 12 "
    data = (
        "\ufeff"
        + spaced_header
        + "\r\n\r\n# comment\r\n"
        + row
        + "\r\n"
    ).encode()
    actual = _core.read_euroc_state(data)
    assert actual.timestamps_ns.tolist() == [10]
    assert actual.positions.tolist() == [[1.0, 2.0, 3.0]]


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\n",
        b"# unrelated\n",
        (HEADER.replace("q_RS_w", "q_SR_w") + "\n").encode(),
        (HEADER + "\n1,1,2\n").encode(),
        (HEADER + "\n1," + ",".join(["0"] * 16) + ",extra\n").encode(),
        (HEADER + "\n1," + ",".join(["0"] * 15) + ",\n").encode(),
        (HEADER + "\n-1," + ",".join(["1"] * 16) + "\n").encode(),
        (HEADER + "\n+1," + ",".join(["1"] * 16) + "\n").encode(),
        (HEADER + "\n9223372036854775808," + ",".join(["1"] * 16) + "\n").encode(),
        (HEADER + "\n1," + ",".join(["1"] * 15) + ",nan\n").encode(),
        (HEADER + "\n1," + ",".join(["1"] * 15) + ",inf\n").encode(),
        (HEADER + "\n1,1,2,3,0,0,0,0," + ",".join(["1"] * 9) + "\n").encode(),
        (HEADER + "\n1," + ",".join(["1"] * 16) + "\0\n").encode(),
    ],
)
def test_malformed_input_rejected(data):
    with pytest.raises(ValueError):
        _core.read_euroc_state(data)


@pytest.mark.parametrize(
    "timestamps",
    [
        (1, 1),
        (2, 1),
    ],
)
def test_duplicate_or_decreasing_timestamps_rejected(timestamps):
    rows = [
        f"{timestamp}," + ",".join(["1"] * 16)
        for timestamp in timestamps
    ]
    with pytest.raises(ValueError, match="strictly increasing"):
        _core.read_euroc_state(
            (HEADER + "\n" + "\n".join(rows) + "\n").encode()
        )


def test_oversized_line_is_rejected_on_decode_and_inspect(tmp_path):
    path = tmp_path / "oversized"
    path.write_bytes((HEADER + "\n").encode() + b"1" * (1024 * 1024 + 1))
    with pytest.raises(ValueError, match="1 MiB"):
        _core.read_euroc_state(path.read_bytes())
    with pytest.raises(sceneio.FormatError, match="1 MiB"):
        sceneio.inspect(path, format="euroc_state")


def test_buffer_protocol_and_mmap_match_bytes(tmp_path):
    data = bytes(_core.write_euroc_state(_trajectory(50)))
    path = tmp_path / "states"
    path.write_bytes(data)
    expected = _core.read_euroc_state(data)
    with (
        path.open("rb") as stream,
        mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped,
    ):
        actual = _core.read_euroc_state(mapped)
        assert _core._buffer_address(mapped) == np.frombuffer(
            mapped, dtype=np.uint8
        ).ctypes.data
    gc.collect()
    _assert_equal(actual, expected)


def test_public_dispatch_detection_inspection_and_capabilities(tmp_path):
    path = tmp_path / "data.csv"
    expected = _trajectory(9)
    sceneio.write(expected, path, format="euroc_state")
    assert sceneio.detect(path) == "euroc_state"
    _assert_equal(sceneio.read(path), expected)
    info = sceneio.inspect(path)
    assert (info.format, info.datatype, info.count, info.shape) == (
        "euroc_state",
        "state_trajectory",
        9,
        (9,),
    )
    assert info.metadata["first_timestamp_ns"] == int(
        expected.timestamps_ns[0]
    )
    assert info.metadata["last_timestamp_ns"] == int(
        expected.timestamps_ns[-1]
    )
    capabilities = sceneio.capabilities("euroc_state")
    assert capabilities.record_type == "StateTrajectory"
    assert capabilities.partial_selectors == ("states",)
    assert capabilities.streams_read and capabilities.streams_write


def test_generic_csv_extension_is_not_claimed(tmp_path):
    path = tmp_path / "arbitrary.csv"
    path.write_text("a,b\n1,2\n", encoding="ascii")
    with pytest.raises(sceneio.FormatError):
        sceneio.detect(path)


@pytest.mark.parametrize(
    "bounds",
    [
        (0, 1),
        (2, 7),
        (8, 10),
    ],
)
def test_partial_states_equal_full_slice(tmp_path, bounds):
    path = tmp_path / "states"
    sceneio.write(_trajectory(10), path, format="euroc_state")
    full = sceneio.read(path)
    actual = sceneio.read_partial(path, states=bounds)
    start, stop = bounds
    for left, right in zip(_fields(actual), _fields(full), strict=True):
        np.testing.assert_array_equal(left, right[start:stop])
    assert actual.pose_convention == full.pose_convention


@pytest.mark.parametrize("bounds", [(-1, 1), (1, 1), (2, 1), (0, 20)])
def test_partial_invalid_bounds_raise(tmp_path, bounds):
    path = tmp_path / "states"
    sceneio.write(_trajectory(3), path, format="euroc_state")
    with pytest.raises((sceneio.FormatError, OverflowError)):
        sceneio.read_partial(path, states=bounds)


def test_partial_validates_unselected_rows():
    data = bytes(_core.write_euroc_state(_trajectory(4)))
    rows = data.splitlines()
    rows[-1] = rows[-1].replace(b",", b",nan,", 1)
    with pytest.raises(ValueError):
        _core.read_euroc_state_states(b"\n".join(rows) + b"\n", 0, 1)


def test_sink_output_is_byte_identical_and_chunked(tmp_path):
    trajectory = _trajectory(5000)
    expected = bytes(_core.write_euroc_state(trajectory))
    path = tmp_path / "states"
    calls = _core._write_to_file(
        _core.write_euroc_state,
        trajectory,
        path,
        _max_chunk=4096,
    )
    assert calls > 3
    assert path.read_bytes() == expected


def test_writer_guard_does_not_truncate_existing_destination(tmp_path):
    path = tmp_path / "states"
    path.write_bytes(b"keep")
    foreign = _trajectory(2, quaternion_order="xyzw")
    with pytest.raises(sceneio.FormatError, match="not representable"):
        sceneio.write(foreign, path, format="euroc_state")
    assert path.read_bytes() == b"keep"


@pytest.mark.parametrize(
    ("metadata", "value"),
    [
        ("quaternion_order", "xyzw"),
        ("quaternion_sign", "canonical_positive_w"),
        ("pose_convention", "reference_to_sensor"),
        ("position_frame", "sensor"),
        ("velocity_frame", "sensor"),
        ("bias_frame", "reference"),
        ("position_unit", "millimeters"),
        ("velocity_unit", "millimeters_per_second"),
        ("gyro_bias_unit", "degrees_per_second"),
        ("accel_bias_unit", "standard_gravity"),
    ],
)
def test_writer_guards_unrepresentable_metadata(metadata, value):
    if metadata == "quaternion_sign":
        arrays = list(_arrays(1))
        arrays[2][:, 0] = np.abs(arrays[2][:, 0])
        trajectory = _core.state_trajectory(
            *arrays, quaternion_sign=value
        )
    else:
        trajectory = _trajectory(1, **{metadata: value})
    with pytest.raises(ValueError, match="not representable"):
        _core.write_euroc_state(trajectory)


def test_writer_revalidates_mutable_zero_copy_views():
    trajectory = _trajectory(3)
    trajectory.timestamps_ns[1] = trajectory.timestamps_ns[0]
    with pytest.raises(ValueError, match="timestamps"):
        _core.write_euroc_state(trajectory)

    trajectory = _trajectory(3)
    trajectory.positions[1, 1] = np.nan
    with pytest.raises(ValueError, match="finite"):
        _core.write_euroc_state(trajectory)

    trajectory = _trajectory(3)
    trajectory.quaternions[1] = 0
    with pytest.raises(ValueError, match="nonzero"):
        _core.write_euroc_state(trajectory)


def test_mmap_public_read_avoids_whole_file_python_bytes(tmp_path):
    trajectory = _trajectory(30_000)
    path = tmp_path / "states"
    sceneio.write(trajectory, path, format="euroc_state")
    size = path.stat().st_size

    tracemalloc.start()
    data = path.read_bytes()
    _core.read_euroc_state(data)
    _, bytes_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del data

    tracemalloc.start()
    sceneio.read(path)
    _, mmap_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert bytes_peak >= size * 0.8
    assert mmap_peak < max(1_000_000, size * 0.1)


def test_inspection_is_streaming_and_does_not_construct_state_arrays(tmp_path):
    trajectory = _trajectory(30_000)
    path = tmp_path / "states"
    sceneio.write(trajectory, path, format="euroc_state")
    tracemalloc.start()
    info = sceneio.inspect(path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert info.count == trajectory.num_states
    assert peak < 2_000_000


def test_randomized_differential_roundtrips():
    for seed in range(40):
        expected = _trajectory(seed % 19, seed)
        encoded = bytes(_core.write_euroc_state(expected))
        actual = _core.read_euroc_state(memoryview(encoded))
        _assert_equal(actual, expected)
        oracle_timestamps, oracle_values = _oracle_decode(encoded)
        np.testing.assert_array_equal(
            oracle_timestamps, expected.timestamps_ns
        )
        assert np.all(np.isfinite(oracle_values))


def test_randomized_malformed_rows_match_independent_oracle():
    rng = np.random.default_rng(1907)
    base = bytes(_core.write_euroc_state(_trajectory(8))).splitlines()
    invalid_tokens = (b"", b"x", b"nan", b"inf", b"-1", b"1e9999")
    for _ in range(200):
        rows = list(base)
        row_index = int(rng.integers(1, len(rows)))
        fields = rows[row_index].split(b",")
        field_index = int(rng.integers(0, len(fields)))
        fields[field_index] = invalid_tokens[
            int(rng.integers(0, len(invalid_tokens)))
        ]
        rows[row_index] = b",".join(fields)
        data = b"\n".join(rows) + b"\n"
        oracle_valid = _oracle_accepts(data)
        try:
            _core.read_euroc_state(data)
        except ValueError:
            native_valid = False
        else:
            native_valid = True
        assert native_valid is oracle_valid
