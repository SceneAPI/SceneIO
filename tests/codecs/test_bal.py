"""Independent parity, convention, malformed, mmap, sink, and memory tests for BAL."""

from __future__ import annotations

import gc
import math
import mmap
import tracemalloc

import numpy as np
import pytest

import sceneio
from sceneio import _core

F = np.diag([1.0, -1.0, -1.0])
INT32_MAX = np.iinfo(np.int32).max


def angle_axis_to_matrix(angle_axis) -> np.ndarray:
    """Independent NumPy Rodrigues implementation."""
    vector = np.asarray(angle_axis, dtype=np.float64)
    theta = np.linalg.norm(vector)
    if theta < 1e-12:
        skew = np.array(
            [
                [0.0, -vector[2], vector[1]],
                [vector[2], 0.0, -vector[0]],
                [-vector[1], vector[0], 0.0],
            ]
        )
        return np.eye(3) + skew + 0.5 * (skew @ skew)
    axis = vector / theta
    skew = np.array(
        [
            [0.0, -axis[2], axis[1]],
            [axis[2], 0.0, -axis[0]],
            [-axis[1], axis[0], 0.0],
        ]
    )
    return (
        np.eye(3) * math.cos(theta)
        + (1.0 - math.cos(theta)) * np.outer(axis, axis)
        + math.sin(theta) * skew
    )


def quaternion_to_matrix(quaternion) -> np.ndarray:
    w, x, y, z = np.asarray(quaternion, np.float64)
    w, x, y, z = np.array([w, x, y, z]) / np.linalg.norm(
        [w, x, y, z]
    )
    return np.array(
        [
            [
                1 - 2 * (y * y + z * z),
                2 * (x * y - w * z),
                2 * (x * z + w * y),
            ],
            [
                2 * (x * y + w * z),
                1 - 2 * (x * x + z * z),
                2 * (y * z - w * x),
            ],
            [
                2 * (x * z - w * y),
                2 * (y * z + w * x),
                1 - 2 * (x * x + y * y),
            ],
        ]
    )


def oracle_read(data: bytes) -> dict:
    tokens = data.decode("ascii").split()
    if len(tokens) < 3:
        raise ValueError("missing header")
    try:
        camera_count, point_count, observation_count = map(
            int, tokens[:3]
        )
    except ValueError as exc:
        raise ValueError("bad header") from exc
    if (
        min(camera_count, point_count, observation_count) < 0
        or max(camera_count, point_count, observation_count) > INT32_MAX
    ):
        raise ValueError("bad counts")
    expected = (
        3
        + observation_count * 4
        + camera_count * 9
        + point_count * 3
    )
    if len(tokens) != expected:
        raise ValueError("token count")
    cursor = 3
    observations = []
    for _ in range(observation_count):
        camera = int(tokens[cursor])
        point = int(tokens[cursor + 1])
        x = float(tokens[cursor + 2])
        y = float(tokens[cursor + 3])
        cursor += 4
        if (
            camera < 0
            or camera >= camera_count
            or point < 0
            or point >= point_count
            or not np.isfinite([x, y]).all()
        ):
            raise ValueError("bad observation")
        observations.append((camera, point, x, y))
    cameras = np.asarray(
        [float(value) for value in tokens[cursor : cursor + 9 * camera_count]],
        dtype=np.float64,
    ).reshape(camera_count, 9)
    cursor += 9 * camera_count
    points = np.asarray(
        [float(value) for value in tokens[cursor:]],
        dtype=np.float64,
    ).reshape(point_count, 3)
    if (
        not np.isfinite(cameras).all()
        or not np.isfinite(points).all()
        or (camera_count and np.any(cameras[:, 6] <= 0))
    ):
        raise ValueError("bad parameter")
    return {
        "camera_count": camera_count,
        "point_count": point_count,
        "observation_count": observation_count,
        "observations": observations,
        "cameras": cameras,
        "points": points,
    }


def oracle_write(cameras, points, observations) -> bytes:
    cameras = np.asarray(cameras, dtype=np.float64).reshape(-1, 9)
    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    lines = [f"{len(cameras)} {len(points)} {len(observations)}"]
    lines.extend(
        f"{camera} {point} {x:.17g} {y:.17g}"
        for camera, point, x, y in observations
    )
    for camera in cameras:
        lines.extend(f"{value:.17g}" for value in camera)
    for point in points:
        lines.extend(f"{value:.17g}" for value in point)
    return ("\n".join(lines) + "\n").encode()


CAMERAS = np.array(
    [
        [0, 0, 0, 1, 2, 3, 800, 0.125, 0.03125],
        [0, 0, np.pi / 2, 4, 5, 6, 1000, 0.25, 0.0625],
    ],
    dtype=np.float64,
)
POINTS = np.array(
    [[1.5, -2.5, 3.5], [0.5, 0.25, -0.5], [-1.0, 2.0, 0.0]],
    dtype=np.float64,
)
# Deliberately not grouped by point or camera. The writer emits a deterministic
# point-major order because Reconstruction stores tracks per point.
OBSERVATIONS = [
    (1, 2, 5.0, 6.0),
    (0, 0, 10.5, 20.25),
    (0, 1, 1.25, -2.5),
    (1, 0, -3.5, 4.5),
]
FIXTURE = oracle_write(CAMERAS, POINTS, OBSERVATIONS)

GOLDEN = (
    b"1 1 1\n"
    b"0 0 10.5 20.25\n"
    b"0\n0\n0\n"
    b"1\n2\n3\n"
    b"800\n0.5\n0.25\n"
    b"1.5\n-2.5\n3.5\n"
)


def assert_reconstruction_matches_raw(record, raw):
    assert isinstance(record, _core.Reconstruction)
    assert (
        record.num_cameras,
        record.num_images,
        record.num_points3D,
    ) == (
        raw["camera_count"],
        raw["camera_count"],
        raw["point_count"],
    )
    np.testing.assert_array_equal(
        record.image_ids,
        np.arange(1, raw["camera_count"] + 1, dtype=np.uint32),
    )
    np.testing.assert_array_equal(
        record.image_camera_ids,
        np.arange(1, raw["camera_count"] + 1, dtype=np.uint32),
    )
    np.testing.assert_array_equal(
        record.point3D_ids,
        np.arange(1, raw["point_count"] + 1, dtype=np.uint64),
    )
    assert tuple(record.image_names) == ("",) * raw["camera_count"]
    np.testing.assert_array_equal(record.xyz, raw["points"])
    np.testing.assert_array_equal(
        record.rgb, np.zeros((raw["point_count"], 3), dtype=np.uint8)
    )
    np.testing.assert_array_equal(
        record.errors, np.full(raw["point_count"], -1.0)
    )
    for index, parameters in enumerate(raw["cameras"]):
        camera = record.cameras[index]
        assert camera.id == index + 1
        assert camera.model == "RADIAL"
        assert (camera.width, camera.height) == (0, 0)
        np.testing.assert_array_equal(
            camera.params,
            [parameters[6], 0.0, 0.0, parameters[7], parameters[8]],
        )
        np.testing.assert_allclose(
            quaternion_to_matrix(record.quaternions[index]),
            F @ angle_axis_to_matrix(parameters[:3]),
            atol=2e-14,
        )
        np.testing.assert_array_equal(
            record.translations[index], F @ parameters[3:6]
        )


def test_oracle_write_sceneio_read_parity_and_conventions():
    raw = oracle_read(FIXTURE)
    record = _core.read_bal(FIXTURE)
    assert_reconstruction_matches_raw(record, raw)


def test_sceneio_write_oracle_read_and_observation_preservation():
    record = _core.read_bal(FIXTURE)
    written = oracle_read(bytes(_core.write_bal(record)))
    assert written["camera_count"] == len(CAMERAS)
    assert written["point_count"] == len(POINTS)
    np.testing.assert_array_equal(written["points"], POINTS)
    for actual, expected in zip(written["cameras"], CAMERAS, strict=True):
        np.testing.assert_allclose(
            angle_axis_to_matrix(actual[:3]),
            angle_axis_to_matrix(expected[:3]),
            atol=2e-14,
        )
        np.testing.assert_array_equal(actual[3:], expected[3:])
    assert set(written["observations"]) == set(OBSERVATIONS)


def test_deterministic_golden_writer_bytes():
    record = _core.read_bal(GOLDEN)
    assert bytes(_core.write_bal(record)) == GOLDEN
    assert bytes(_core.write_bal(record)) == bytes(_core.write_bal(record))


def test_projection_frame_conversion_is_consistent():
    record = _core.read_bal(FIXTURE)
    for camera_index, point_index, observed_x, observed_y in OBSERVATIONS:
        raw_camera = CAMERAS[camera_index]
        point = POINTS[point_index]
        bal_camera_point = (
            angle_axis_to_matrix(raw_camera[:3]) @ point
            + raw_camera[3:6]
        )
        normalized = -bal_camera_point[:2] / bal_camera_point[2]
        radius2 = np.dot(normalized, normalized)
        distortion = (
            1
            + raw_camera[7] * radius2
            + raw_camera[8] * radius2**2
        )
        projected_bal = raw_camera[6] * distortion * normalized

        scene_camera_point = (
            quaternion_to_matrix(record.quaternions[camera_index]) @ point
            + record.translations[camera_index]
        )
        projected_scene = (
            raw_camera[6]
            * distortion
            * scene_camera_point[:2]
            / scene_camera_point[2]
        )
        np.testing.assert_allclose(
            projected_scene,
            [projected_bal[0], -projected_bal[1]],
            atol=2e-12,
        )
        # Fixture coordinates need not be on the projection; this pins only
        # the format/record convention relation.
        assert np.isfinite([observed_x, observed_y]).all()


def test_zero_and_pi_angle_axis_branches():
    cameras = CAMERAS.copy()
    cameras[0, :3] = 0
    cameras[1, :3] = [np.pi, 0, 0]
    encoded = oracle_write(cameras, POINTS, OBSERVATIONS)
    record = _core.read_bal(encoded)
    zero_components = np.asarray(record.quaternions) == 0.0
    assert not np.signbit(np.asarray(record.quaternions)[zero_components]).any()
    for index in range(2):
        np.testing.assert_allclose(
            quaternion_to_matrix(record.quaternions[index]),
            F @ angle_axis_to_matrix(cameras[index, :3]),
            atol=2e-14,
        )
    rewritten = oracle_read(bytes(_core.write_bal(record)))
    for index in range(2):
        np.testing.assert_allclose(
            angle_axis_to_matrix(rewritten["cameras"][index, :3]),
            angle_axis_to_matrix(cameras[index, :3]),
            atol=2e-14,
        )


def test_randomized_valid_differential_roundtrips():
    rng = np.random.default_rng(20260724)
    for _ in range(50):
        camera_count = int(rng.integers(1, 5))
        point_count = int(rng.integers(1, 9))
        cameras = np.empty((camera_count, 9), dtype=np.float64)
        cameras[:, :3] = rng.normal(0, 0.7, (camera_count, 3))
        cameras[:, 3:6] = rng.normal(0, 4, (camera_count, 3))
        cameras[:, 6] = rng.uniform(100, 2000, camera_count)
        cameras[:, 7:] = rng.normal(0, 0.05, (camera_count, 2))
        points = rng.normal(0, 10, (point_count, 3))
        observations = []
        for point in range(point_count):
            for camera in rng.choice(
                camera_count,
                size=int(rng.integers(1, camera_count + 1)),
                replace=False,
            ):
                x, y = rng.normal(0, 500, 2)
                observations.append(
                    (int(camera), point, float(x), float(y))
                )
        rng.shuffle(observations)
        raw = {
            "camera_count": camera_count,
            "point_count": point_count,
            "observation_count": len(observations),
            "cameras": cameras,
            "points": points,
        }
        record = _core.read_bal(
            oracle_write(cameras, points, observations)
        )
        assert_reconstruction_matches_raw(record, raw)
        rewritten = oracle_read(bytes(_core.write_bal(record)))
        assert set(rewritten["observations"]) == set(observations)
        np.testing.assert_array_equal(rewritten["points"], points)
        for actual, expected in zip(
            rewritten["cameras"], cameras, strict=True
        ):
            np.testing.assert_allclose(
                angle_axis_to_matrix(actual[:3]),
                angle_axis_to_matrix(expected[:3]),
                atol=5e-14,
            )
            np.testing.assert_array_equal(actual[3:], expected[3:])


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "missing field"),
        (b"1 1", "missing field"),
        (b"-1 0 0", "bad integer"),
        (f"{INT32_MAX + 1} 0 0".encode(), "int32"),
        (b"100 100 100\n", "file size"),
        (
            b"1 1 1\n1 0 0 0\n" + b"0\n" * 6 + b"1\n0\n0\n0\n0\n0\n",
            "camera index",
        ),
        (
            b"1 1 1\n0 1 0 0\n" + b"0\n" * 6 + b"1\n0\n0\n0\n0\n0\n",
            "point index",
        ),
        (
            b"1 1 1\n0 0 nan 0\n" + b"0\n" * 6 + b"1\n0\n0\n0\n0\n0\n",
            "finite",
        ),
        (
            b"1 0 0\n" + b"0\n" * 6 + b"0\n0\n0\n",
            "positive",
        ),
        (
            b"1 0 0\n1e300\n1e300\n1e300\n0\n0\n0\n1\n0\n0\n",
            "norm",
        ),
        (GOLDEN + b"extra\n", "trailing"),
    ],
)
def test_malformed_inputs_reject(data, message):
    with pytest.raises(ValueError, match=message):
        _core.read_bal(data)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"1 1",
        b"-1 0 0",
        f"{INT32_MAX + 1} 0 0".encode(),
        b"100 100 100\n",
    ],
)
def test_inspector_rejects_invalid_headers(data):
    with pytest.raises(ValueError):
        _core._inspect_bal(data)


def test_whitespace_and_crlf_match_reference_token_grammar():
    wrapped = b"\r\n\t".join(GOLDEN.split())
    assert_reconstruction_matches_raw(
        _core.read_bal(wrapped), oracle_read(wrapped)
    )


def test_public_detect_read_write_and_inspect(tmp_path):
    path = tmp_path / "problem.bal"
    path.write_bytes(FIXTURE)
    assert sceneio.detect(path) == "bal"
    record = sceneio.read(path)
    assert_reconstruction_matches_raw(record, oracle_read(FIXTURE))
    info = sceneio.inspect(path)
    assert info.format == "bal"
    assert info.datatype == "sparse_model"
    assert info.shape == (2,)
    assert info.dtype == "float64"
    assert info.count == 2
    assert info.metadata == {
        "num_cameras": 2,
        "num_images": 2,
        "num_points3D": 3,
        "num_observations": 4,
    }
    output = tmp_path / "copy.bal"
    sceneio.write(record, output)
    assert oracle_read(output.read_bytes())["observation_count"] == 4

    text_path = tmp_path / "problem.txt"
    text_path.write_bytes(FIXTURE)
    assert isinstance(
        sceneio.read(text_path, format="bal"), _core.Reconstruction
    )
    with pytest.raises(sceneio.FormatError, match="cannot detect"):
        sceneio.detect(text_path)


def test_mmap_equals_bytes_and_decode_owns_result(tmp_path):
    path = tmp_path / "mapped.bal"
    path.write_bytes(FIXTURE)
    expected = _core.read_bal(FIXTURE)
    with path.open("rb") as stream:
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        actual = _core.read_bal(mapped)
        mapped.close()
    np.testing.assert_array_equal(actual.xyz, expected.xyz)
    np.testing.assert_array_equal(
        actual.quaternions, expected.quaternions
    )
    assert bytes(_core.write_bal(actual)) == bytes(
        _core.write_bal(expected)
    )


def test_sparse_large_inspect_reads_only_header_with_bounded_memory(tmp_path):
    path = tmp_path / "large.bal"
    with path.open("wb") as stream:
        stream.write(b"1 1 0\n")
        stream.truncate(64 * 1024 * 1024)
    gc.collect()
    tracemalloc.start()
    try:
        info = sceneio.inspect(path)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert info.metadata["num_cameras"] == 1
    assert info.metadata["num_points3D"] == 1
    assert info.metadata["num_observations"] == 0
    assert peak < 1024 * 1024


def _large_fixture(point_count=12_000):
    cameras = np.array(
        [[0, 0, 0, 0, 0, 0, 800, 0.01, 0.001]],
        dtype=np.float64,
    )
    points = np.arange(point_count * 3, dtype=np.float64).reshape(
        point_count, 3
    )
    observations = [
        (0, point, float(point), float(-point))
        for point in range(point_count)
    ]
    return oracle_write(cameras, points, observations)


def test_chunked_file_sink_is_identical_and_avoids_output_python_bytes(
    tmp_path,
):
    record = _core.read_bal(_large_fixture())
    gc.collect()
    tracemalloc.start()
    try:
        expected = bytes(_core.write_bal(record))
        _, buffer_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    path = tmp_path / "sink.bal"
    gc.collect()
    tracemalloc.start()
    try:
        calls = _core._write_to_file(
            _core.write_bal,
            record,
            path,
            _max_chunk=4096,
            _test_short_write=17,
        )
        _, sink_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert calls >= 4
    assert path.read_bytes() == expected
    assert buffer_peak > len(expected) * 0.8
    assert sink_peak < len(expected) * 0.2


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda record: record.image_ids.__setitem__(0, 2),
            "contiguous one-based",
        ),
        (
            lambda record: record.quaternions.__setitem__((0, 0), np.nan),
            "quaternion",
        ),
        (
            lambda record: record.rgb.__setitem__((0, 0), 1),
            "colors",
        ),
        (
            lambda record: record.errors.__setitem__(0, 0.0),
            "errors",
        ),
    ],
)
def test_writer_guards_unrepresentable_record_fields(
    tmp_path, mutator, message
):
    record = _core.read_bal(GOLDEN)
    mutator(record)
    path = tmp_path / "existing.bal"
    path.write_bytes(b"keep")
    with pytest.raises(ValueError, match=message):
        _core.write_bal(record)
    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.write(record, path, format="bal")
    assert path.read_bytes() == b"keep"


def test_writer_rejects_noncanonical_camera_model():
    bundler = (
        b"# Bundle file v0.3\n1 0\n"
        b"800 0.5 0\n"
        b"1 0 0\n0 1 0\n0 0 1\n0 0 0\n"
    )
    record = _core.read_bundler(bundler)
    with pytest.raises(ValueError, match="RADIAL"):
        _core.write_bal(record)


def test_very_long_token_errors_are_bounded():
    data = b"1 0 0\n" + b"9" * (1024 * 1024 + 1)
    with pytest.raises(ValueError, match="1 MiB") as caught:
        _core.read_bal(data)
    assert len(str(caught.value)) < 256
