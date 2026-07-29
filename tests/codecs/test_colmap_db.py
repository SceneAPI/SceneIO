"""COLMAP SQLite database record, oracle, partial-read, and failure tests."""

from __future__ import annotations

import gc
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np
import pytest

import sceneio
from sceneio import _core
from sceneio import colmap_db as db_contract

_PROFILE_SCHEMA_SNAPSHOTS = json.loads(
    (
        Path(__file__).parents[1]
        / "fixtures"
        / "colmap_db_profiles"
        / "schema_snapshots_v1.json"
    ).read_text(encoding="utf-8")
)["profiles"]


def _empty_profile_database(path: Path, profile_name: str) -> None:
    profile = db_contract.COLMAP_DATABASE_PROFILES_BY_NAME[profile_name]
    with sqlite3.connect(path) as connection:
        connection.executescript(_core._colmap_db_profile_schema(profile_name))
        connection.execute(f"PRAGMA application_id={profile.application_id}")
        connection.execute(f"PRAGMA user_version={profile.user_version}")
        if profile.ownership_row:
            connection.execute(
                "INSERT INTO maxx_schema_info VALUES(1,1,?,?)",
                ("3.14.0", profile.source_revision),
            )


def test_profile_catalog_matches_python_contract() -> None:
    assert tuple(
        (
            item["name"],
            item["source_revision"],
            item["application_id"],
            item["user_version"],
            item["typed_descriptors"],
            item["generalized_pose_priors"],
            item["recovered_two_view_cameras"],
            item["maxx_extensions"],
            item["has_ownership_row"],
        )
        for item in _core._colmap_db_profiles()
    ) == tuple(
        (
            profile.name,
            profile.source_revision,
            profile.application_id,
            profile.user_version,
            profile.typed_descriptors,
            profile.generalized_pose_priors,
            profile.recovered_two_view_cameras,
            profile.maxx_extensions,
            profile.ownership_row,
        )
        for profile in db_contract.COLMAP_DATABASE_PROFILES
    )


@pytest.mark.parametrize(
    "profile_name",
    [profile.name for profile in db_contract.COLMAP_DATABASE_PROFILES],
)
def test_inspect_identifies_exact_profile(tmp_path, profile_name):
    path = tmp_path / f"{profile_name}.db"
    _empty_profile_database(path, profile_name)

    inspection = _core.inspect_colmap_db(str(path))

    profile = db_contract.COLMAP_DATABASE_PROFILES_BY_NAME[profile_name]
    snapshot = _PROFILE_SCHEMA_SNAPSHOTS[profile_name]
    assert inspection["profile"] == profile_name
    assert inspection["profile_source_revision"] == profile.source_revision
    assert inspection["application_id"] == profile.application_id
    assert inspection["user_version"] == profile.user_version
    assert inspection["schema_signature"] == snapshot["schema_signature"]
    assert snapshot["source_revision"] == profile.source_revision
    assert snapshot["application_id"] == profile.application_id
    assert snapshot["user_version"] == profile.user_version
    connection = sqlite3.connect(path)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
        indexes = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
        ]
    finally:
        connection.close()
    assert tables == snapshot["tables"]
    assert indexes == snapshot["indexes"]


@pytest.mark.parametrize(
    "profile_name",
    [profile.name for profile in db_contract.COLMAP_DATABASE_PROFILES],
)
def test_inspect_rejects_schema_near_miss(tmp_path, profile_name):
    path = tmp_path / f"{profile_name}-changed.db"
    _empty_profile_database(path, profile_name)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE local_extra(value INTEGER)")

    inspection = _core.inspect_colmap_db(str(path))

    assert inspection["profile"] == "unknown"


@pytest.mark.parametrize(
    ("pragma", "value"),
    [("user_version", 123), ("application_id", 123)],
)
def test_inspect_requires_every_identity_component(tmp_path, pragma, value):
    path = tmp_path / f"wrong-{pragma}.db"
    _empty_profile_database(path, "colmap-4.1.1")
    with sqlite3.connect(path) as connection:
        connection.execute(f"PRAGMA {pragma}={value}")

    inspection = _core.inspect_colmap_db(str(path))
    database = _core.read_colmap_db(str(path))

    assert inspection["profile"] == "unknown"
    assert inspection[pragma] == value
    assert database.profile == "unknown"
    assert getattr(database, pragma) == value


@pytest.mark.parametrize(
    "ownership",
    ["missing", "empty_version", "empty_commit", "wrong_schema", "duplicate"],
)
def test_inspect_requires_valid_maxx_ownership_row(tmp_path, ownership):
    path = tmp_path / f"maxx-{ownership}.db"
    _empty_profile_database(path, "maxx-v1")
    with sqlite3.connect(path) as connection:
        if ownership == "missing":
            connection.execute("DELETE FROM maxx_schema_info")
        elif ownership == "empty_version":
            connection.execute(
                "UPDATE maxx_schema_info SET producer_version=''"
            )
        elif ownership == "empty_commit":
            connection.execute(
                "UPDATE maxx_schema_info SET producer_commit=''"
            )
        elif ownership == "wrong_schema":
            connection.execute(
                "UPDATE maxx_schema_info SET schema_version=2"
            )
        else:
            connection.execute(
                "INSERT INTO maxx_schema_info VALUES(2,1,'3.14.0','b')"
            )

    inspection = _core.inspect_colmap_db(str(path))

    assert inspection["profile"] == "unknown"


@pytest.mark.parametrize("profile_name", ["colmap-3.13.0", "colmap-4.1.1"])
def test_read_records_exact_stock_profile_identity(tmp_path, profile_name):
    path = tmp_path / f"{profile_name}.db"
    _empty_profile_database(path, profile_name)

    database = _core.read_colmap_db(str(path))

    assert database.profile == profile_name
    assert database.application_id == 0
    assert (
        database.user_version
        == db_contract.COLMAP_DATABASE_PROFILES_BY_NAME[profile_name].user_version
    )


def test_exact_profile_writer_is_guarded_until_profile_writers_land(tmp_path):
    path = tmp_path / "stock.db"
    _empty_profile_database(path, "colmap-4.1.1")
    database = _core.read_colmap_db(str(path))

    with pytest.raises(ValueError, match="exact profile preservation"):
        _core.write_colmap_db(database, str(tmp_path / "converted.db"))


def test_hybrid_constructor_rejects_application_identity():
    template = _database()
    with pytest.raises(ValueError, match="application_id=0"):
        _core.colmap_database(
            template.cameras,
            [template.feature_at(i) for i in range(template.num_images)],
            template.match_graph,
            prior_focal_length=template.prior_focal_length,
            application_id=123,
        )


def _feature(
    image_id: int,
    name: str,
    *,
    rows: int = 3,
    columns: int = 4,
    keypoint_columns: int = 2,
    camera_id: int = 5,
    keypoints_present: bool = True,
):
    keypoints = (
        np.arange(rows * keypoint_columns, dtype=np.float32).reshape(
            rows, keypoint_columns
        )
        + image_id
    )
    descriptors = (
        np.arange(rows * columns, dtype=np.uint8).reshape(rows, columns) + image_id
    )
    return _core.feature_set(
        keypoints,
        descriptors,
        image_id=image_id,
        image_name=name,
        camera_id=camera_id,
        image_size=(640, 480),
        extractor_type=0,
        time_id=17 if image_id == 2 else None,
        keypoints_present=keypoints_present,
    )


def _graph(
    *,
    raw: np.ndarray | None = None,
    verified: np.ndarray | None = None,
    match_present: bool = True,
    geometry_present: bool = True,
):
    if raw is None:
        raw = np.array([[0, 1], [2, 0]], np.uint32)
    if verified is None:
        verified = np.array([[2, 0]], np.uint32)
    F = np.arange(9, dtype=np.float64).reshape(1, 3, 3)
    E = (np.arange(9, dtype=np.float64) + 20).reshape(1, 3, 3)
    H = (np.arange(9, dtype=np.float64) + 40).reshape(1, 3, 3)
    return _core.match_graph(
        np.array([[2, 11]], np.uint32),
        np.array([0, len(raw)], np.uint64),
        raw,
        np.array([0, len(verified)], np.uint64),
        verified,
        configs=np.array([3 if geometry_present else 0], np.int32),
        fundamental_matrices=F,
        fundamental_present=np.array([geometry_present], np.uint8),
        essential_matrices=E,
        essential_present=np.array([geometry_present], np.uint8),
        homographies=H,
        homography_present=np.array([geometry_present], np.uint8),
        qvecs=np.array([[1.0, 0, 0, 0]], np.float64),
        tvecs=np.array([[1.0, 2.0, 3.0]], np.float64),
        pose_present=np.array([geometry_present], np.uint8),
        match_present=np.array([match_present], np.uint8),
        geometry_present=np.array([geometry_present], np.uint8),
    )


def _database(*, graph=None, features=None):
    camera = _core.camera(
        5,
        1,
        640,
        480,
        np.array([500.0, 501.0, 320.0, 240.0], np.float64),
    )
    if features is None:
        features = [_feature(2, "a.jpg", keypoint_columns=4), _feature(11, "b.jpg")]
    return _core.colmap_database(
        [camera],
        features,
        _graph() if graph is None else graph,
        prior_focal_length=np.array([1], np.uint8),
    )


def _feature_fingerprint(value):
    return (
        value.image_id,
        value.image_name,
        value.camera_id,
        tuple(value.image_size),
        value.time_id,
        value.extractor_type,
        value.keypoints_present,
        value.keypoint_columns,
        value.descriptor_dtype,
        value.descriptor_dim,
        np.asarray(value.keypoints).tobytes(),
        (
            None
            if value.descriptors is None
            else np.asarray(value.descriptors).dtype.str,
            None
            if value.descriptors is None
            else np.asarray(value.descriptors).shape,
            None
            if value.descriptors is None
            else np.asarray(value.descriptors).tobytes(),
        ),
        None if value.scores is None else np.asarray(value.scores).tobytes(),
    )


def _graph_fingerprint(value):
    names = (
        "pair_ids",
        "image_pairs",
        "match_present",
        "geometry_present",
        "match_offsets",
        "matches",
        "verified_offsets",
        "verified_matches",
        "configs",
        "F_present",
        "E_present",
        "H_present",
        "fundamental_matrices",
        "essential_matrices",
        "homographies",
        "pose_present",
        "qvecs",
        "tvecs",
    )
    return tuple(
        (np.asarray(getattr(value, name)).dtype.str, np.asarray(getattr(value, name)).shape,
         np.asarray(getattr(value, name)).tobytes())
        for name in names
    )


def _database_fingerprint(value):
    return (
        value.profile,
        value.application_id,
        value.user_version,
        tuple(
            (
                camera.id,
                camera.model_id,
                camera.width,
                camera.height,
                np.asarray(camera.params).tobytes(),
            )
            for camera in value.cameras
        ),
        np.asarray(value.prior_focal_length).tobytes(),
        tuple(_feature_fingerprint(value.feature_at(i)) for i in range(value.num_images)),
        _graph_fingerprint(value.match_graph),
    )


def test_feature_set_record_dtype_layout_copy_and_lifetime():
    keypoints = np.arange(18, dtype=np.float32).reshape(3, 6)
    descriptors = np.arange(12, dtype=np.uint8).reshape(3, 4)
    scores = np.array([0.1, 0.2, 0.3], np.float32)
    value = _core.feature_set(
        keypoints,
        descriptors,
        scores,
        image_id=7,
        image_name="frame/0007.png",
        camera_id=5,
        image_size=(640, 480),
        extractor_type=2,
        time_id=99,
    )
    keypoints[:] = -1
    descriptors[:] = 0
    scores[:] = 0
    assert value.num_keypoints == 3
    assert value.keypoint_columns == 6
    assert value.descriptor_dtype == "uint8"
    assert value.descriptor_dim == 4
    assert value.time_id == 99
    assert value.keypoints.ctypes.data == value.keypoints.ctypes.data
    assert value.descriptors.ctypes.data == value.descriptors.ctypes.data
    assert value.scores.ctypes.data == value.scores.ctypes.data
    arrays = (value.keypoints, value.descriptors, value.scores)
    expected = tuple(array.copy() for array in arrays)
    del value
    gc.collect()
    for actual, wanted in zip(arrays, expected, strict=True):
        np.testing.assert_array_equal(actual, wanted)


def test_feature_set_float32_descriptors_and_dlpack_view():
    value = _core.feature_set(
        np.ones((2, 2), np.float32),
        np.array([[0.5, 1.5], [2.5, 3.5]], np.float32),
    )
    assert value.descriptor_dtype == "float32"
    copied = np.from_dlpack(value.keypoints)
    assert copied.ctypes.data == value.keypoints.ctypes.data
    np.testing.assert_array_equal(copied, value.keypoints)


@pytest.mark.parametrize("columns", [2, 4, 6])
def test_feature_set_accepts_every_colmap_keypoint_layout(columns):
    value = _core.feature_set(np.zeros((3, columns), np.float32))
    assert value.keypoints.shape == (3, columns)


@pytest.mark.parametrize(
        ("keypoints", "descriptors", "message"),
    [
        (np.zeros((2, 3), np.float32), None, "2\\|4\\|6"),
        (np.zeros((2, 2), np.float32), np.zeros((3, 4), np.uint8), "must be \\(N,D\\)"),
        (np.zeros((2, 2), np.float32), np.zeros((2, 4), np.int8), "uint8 or float32"),
    ],
)
def test_feature_set_rejects_bad_layouts(keypoints, descriptors, message):
    with pytest.raises((TypeError, ValueError), match=message):
        _core.feature_set(keypoints, descriptors)


def test_feature_set_normalizes_foreign_keypoint_dtype_to_canonical_float32():
    value = _core.feature_set(np.array([[1.25, 2.5]], np.float64))
    assert value.keypoints.dtype == np.float32
    np.testing.assert_array_equal(value.keypoints, [[1.25, 2.5]])


def test_feature_set_rejects_nonfinite_and_descriptor_metadata_without_data():
    keypoints = np.zeros((1, 2), np.float32)
    keypoints[0, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        _core.feature_set(keypoints)
    with pytest.raises(ValueError, match="extractor_type"):
        _core.feature_set(np.zeros((0, 2), np.float32), extractor_type=0)


def test_match_graph_ragged_fields_and_colmap_pair_ids():
    value = _graph()
    assert value.num_pairs == 1
    assert value.num_matches == 2
    assert value.num_verified_matches == 1
    assert value.pair_ids.tolist() == [2 * 2_147_483_647 + 11]
    assert value.image_pairs.tolist() == [[2, 11]]
    assert value.quaternion_order == "wxyz"


def test_match_graph_scores_keep_owner_alive():
    value = _core.match_graph(
        np.array([[2, 11]], np.uint32),
        np.array([0, 1], np.uint64),
        np.array([[0, 0]], np.uint32),
        np.array([0, 0], np.uint64),
        np.empty((0, 2), np.uint32),
        scores=np.array([0.25], np.float32),
        geometry_present=np.array([0], np.uint8),
    )
    scores = value.scores
    assert scores.base is not None
    del value
    gc.collect()
    np.testing.assert_array_equal(scores, np.array([0.25], np.float32))


@pytest.mark.parametrize(
    "call",
    [
        lambda: _core.match_graph(
            np.array([[11, 2]], np.uint32),
            np.array([0, 0], np.uint64),
            np.empty((0, 2), np.uint32),
            np.array([0, 0], np.uint64),
            np.empty((0, 2), np.uint32),
        ),
        lambda: _core.match_graph(
            np.array([[2, 11]], np.uint32),
            np.array([1, 1], np.uint64),
            np.empty((0, 2), np.uint32),
            np.array([0, 0], np.uint64),
            np.empty((0, 2), np.uint32),
        ),
        lambda: _core.match_graph(
            np.array([[2, 11]], np.uint32),
            np.array([0, 1], np.uint64),
            np.empty((0, 2), np.uint32),
            np.array([0, 0], np.uint64),
            np.empty((0, 2), np.uint32),
        ),
        lambda: _core.match_graph(
            np.array([[2, 11]], np.uint32),
            np.array([0, 1], np.uint64),
            np.array([[0, 0]], np.uint32),
            np.array([0, 0], np.uint64),
            np.empty((0, 2), np.uint32),
            match_present=np.array([0], np.uint8),
            geometry_present=np.array([0], np.uint8),
        ),
    ],
)
def test_match_graph_rejects_invalid_pairs_offsets_and_presence(call):
    with pytest.raises(ValueError):
        call()


def test_database_rejects_out_of_range_match_indices_and_camera_mismatch():
    graph = _core.match_graph(
        np.array([[2, 11]], np.uint32),
        np.array([0, 1], np.uint64),
        np.array([[99, 0]], np.uint32),
        np.array([0, 0], np.uint64),
        np.empty((0, 2), np.uint32),
        geometry_present=np.array([0], np.uint8),
    )
    with pytest.raises(ValueError, match="index exceeds"):
        _database(graph=graph)

    wrong_size = _core.feature_set(
        np.zeros((0, 2), np.float32),
        image_id=2,
        image_name="a",
        camera_id=5,
        image_size=(1, 1),
    )
    with pytest.raises(ValueError, match="image_size"):
        _database(features=[wrong_size])


def test_sceneio_roundtrip_sqlite_oracle_and_all_geometry_fields(tmp_path):
    path = tmp_path / "database.db"
    expected = _database()
    sceneio.write(expected, path)
    assert sceneio.detect(path) == "colmap_db"
    actual = sceneio.read(path)
    assert _database_fingerprint(actual) == _database_fingerprint(expected)

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (3_140_002,)
        assert connection.execute(
            "SELECT image_id,name,camera_id,time_id FROM images ORDER BY image_id"
        ).fetchall() == [(2, "a.jpg", 5, 17), (11, "b.jpg", 5, None)]
        pair_id, rows, cols, data = connection.execute(
            "SELECT pair_id,rows,cols,data FROM matches"
        ).fetchone()
        assert pair_id == 2 * 2_147_483_647 + 11
        assert (rows, cols) == (2, 2)
        np.testing.assert_array_equal(
            np.frombuffer(data, np.uint32).reshape(rows, cols),
            expected.match_graph.matches,
        )
        geometry = connection.execute(
            "SELECT rows,cols,data,config,F,E,H,qvec,tvec "
            "FROM two_view_geometries"
        ).fetchone()
        assert geometry[:2] == (1, 2)
        assert geometry[3] == 3
        for blob, source in zip(
            geometry[4:7],
            (
                expected.match_graph.fundamental_matrices[0],
                expected.match_graph.essential_matrices[0],
                expected.match_graph.homographies[0],
            ),
            strict=True,
        ):
            np.testing.assert_array_equal(np.frombuffer(blob, np.float64).reshape(3, 3), source)
        np.testing.assert_array_equal(np.frombuffer(geometry[7], np.float64), [1, 0, 0, 0])
        np.testing.assert_array_equal(np.frombuffer(geometry[8], np.float64), [1, 2, 3])


def test_pycolmap_reads_sceneio_writer(tmp_path):
    pycolmap = pytest.importorskip("pycolmap")
    path = tmp_path / "sceneio.db"
    sceneio.write(_database(), path)
    database = pycolmap.Database.open(path)
    try:
        assert database.num_cameras() == 1
        assert database.num_images() == 2
        np.testing.assert_array_equal(
            database.read_keypoints(2),
            _database().feature(2).keypoints,
        )
        np.testing.assert_array_equal(
            database.read_descriptors(11).data,
            _database().feature(11).descriptors,
        )
        np.testing.assert_array_equal(
            database.read_matches(2, 11),
            _database().match_graph.matches,
        )
        geometry = database.read_two_view_geometry(2, 11)
        np.testing.assert_array_equal(
            geometry.inlier_matches,
            _database().match_graph.verified_matches,
        )
        np.testing.assert_array_equal(geometry.F, np.arange(9).reshape(3, 3))
    finally:
        database.close()


def test_sceneio_reads_pycolmap_writer(tmp_path):
    pycolmap = pytest.importorskip("pycolmap")
    path = tmp_path / "pycolmap.db"
    database = pycolmap.Database.open(path)
    camera = pycolmap.Camera.create_from_model_id(
        5, pycolmap.CameraModelId.PINHOLE, 500.0, 640, 480
    )
    camera.params = np.array([500.0, 501.0, 320.0, 240.0])
    database.write_camera(camera, True)
    for image_id, name in ((2, "a.jpg"), (11, "b.jpg")):
        database.write_image(
            pycolmap.Image(name=name, camera_id=5, image_id=image_id), True
        )
        keypoints = np.arange(8, dtype=np.float32).reshape(2, 4) + image_id
        descriptors = np.arange(16, dtype=np.uint8).reshape(2, 8) + image_id
        database.write_keypoints(image_id, keypoints)
        database.write_descriptors(
            image_id,
            pycolmap.FeatureDescriptors(
                pycolmap.FeatureExtractorType.SIFT, descriptors
            ),
        )
    database.write_matches(11, 2, np.array([[1, 0]], np.uint32))
    geometry = pycolmap.TwoViewGeometry()
    geometry.inlier_matches = np.array([[1, 0]], np.uint32)
    geometry.F = np.eye(3)
    database.write_two_view_geometry(11, 2, geometry)
    database.close()

    value = sceneio.read(path)
    assert value.image_ids == [2, 11]
    assert value.match_graph.image_pairs.tolist() == [[2, 11]]
    assert value.match_graph.pair_ids.tolist() == [2 * 2_147_483_647 + 11]
    # pycolmap canonicalizes the unordered (11,2) request to pair (2,11)
    # and swaps match columns to preserve endpoint meaning.
    np.testing.assert_array_equal(value.match_graph.matches, [[0, 1]])
    np.testing.assert_array_equal(value.match_graph.fundamental_matrices[0], np.eye(3))


def test_absent_and_present_empty_rows_roundtrip_distinctly(tmp_path):
    missing = _core.feature_set(
        np.empty((0, 2), np.float32),
        image_id=2,
        image_name="a",
        camera_id=5,
        image_size=(640, 480),
        keypoints_present=False,
    )
    present = _core.feature_set(
        np.empty((0, 2), np.float32),
        np.empty((0, 8), np.uint8),
        image_id=11,
        image_name="b",
        camera_id=5,
        image_size=(640, 480),
        extractor_type=0,
        keypoints_present=True,
    )
    graph = _core.match_graph(
        np.array([[2, 11]], np.uint32),
        np.array([0, 0], np.uint64),
        np.empty((0, 2), np.uint32),
        np.array([0, 0], np.uint64),
        np.empty((0, 2), np.uint32),
        match_present=np.array([1], np.uint8),
        geometry_present=np.array([0], np.uint8),
    )
    value = _database(features=[missing, present], graph=graph)
    path = tmp_path / "empty.db"
    sceneio.write(value, path)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT image_id,rows,cols,typeof(data),length(data) "
            "FROM keypoints ORDER BY image_id"
        ).fetchall() == [(11, 0, 2, "blob", 0)]
        assert connection.execute(
            "SELECT image_id,rows,cols,typeof(data),length(data) FROM descriptors"
        ).fetchall() == [(11, 0, 8, "blob", 0)]
        assert connection.execute(
            "SELECT rows,cols,typeof(data),length(data) FROM matches"
        ).fetchall() == [(0, 2, "blob", 0)]
        assert connection.execute("SELECT count(*) FROM two_view_geometries").fetchone() == (
            0,
        )
    decoded = sceneio.read(path)
    assert not decoded.feature(2).keypoints_present
    assert decoded.feature(11).keypoints_present
    assert decoded.feature(11).descriptors.shape == (0, 8)
    assert decoded.match_graph.match_present.tolist() == [1]
    assert decoded.match_graph.geometry_present.tolist() == [0]


def test_partial_image_and_pair_equal_slices_of_full_read(tmp_path):
    path = tmp_path / "partial.db"
    sceneio.write(_database(), path)
    full = sceneio.read(path)
    selected_image = sceneio.read_partial(path, image_id=11)
    selected_pair = sceneio.read_partial(path, pair=(11, 2))
    assert _feature_fingerprint(selected_image) == _feature_fingerprint(full.feature(11))
    assert _graph_fingerprint(selected_pair) == _graph_fingerprint(full.match_graph)
    assert sceneio.capabilities("colmap_db").partial_selectors == ("image_id", "pair")


def test_inspect_matches_decoded_metadata_without_blob_arrays(tmp_path):
    path = tmp_path / "inspect.db"
    sceneio.write(_database(), path)
    info = sceneio.inspect(path)
    assert info.format == "colmap_db"
    assert info.datatype == "match_graph"
    assert info.count == 2
    assert info.shape == (2,)
    assert info.metadata["num_cameras"] == 1
    assert info.metadata["num_matches"] == 2
    assert info.metadata["num_verified_matches"] == 1
    assert info.metadata["descriptor_dimensions"] == (4,)
    assert info.metadata["image_ids"] == (2, 11)
    assert [(item.name, item.shape, item.dtype) for item in info.arrays] == [
        ("2/keypoints", (3, 4), "float32"),
        ("2/descriptors", (3, 4), "uint8"),
        ("11/keypoints", (3, 2), "float32"),
        ("11/descriptors", (3, 4), "uint8"),
    ]


def test_inspect_large_blob_has_bounded_python_allocation(tmp_path):
    rows, columns = 2_000_000, 8
    large = _core.feature_set(
        np.zeros((rows, 2), np.float32),
        np.zeros((rows, columns), np.uint8),
        image_id=2,
        image_name="large",
        camera_id=5,
        image_size=(640, 480),
        extractor_type=0,
    )
    path = tmp_path / "large.db"
    sceneio.write(_database(features=[large], graph=_core.match_graph(
        np.empty((0, 2), np.uint32),
        np.array([0], np.uint64),
        np.empty((0, 2), np.uint32),
        np.array([0], np.uint64),
        np.empty((0, 2), np.uint32),
    )), path)
    del large
    gc.collect()
    tracemalloc.start()
    info = sceneio.inspect(path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert info.metadata["num_images"] == 1
    assert info.metadata["descriptor_dimensions"] == (columns,)
    assert peak < 512 * 1024


def test_transaction_rolls_back_injected_failures(tmp_path):
    path = tmp_path / "rollback.db"
    expected = _database()
    _core.write_colmap_db(expected, str(path))
    before = _database_fingerprint(_core.read_colmap_db(str(path)))
    for stage in (1, 2):
        with pytest.raises(RuntimeError, match="injected failure"):
            _core.write_colmap_db(expected, str(path), _test_fail_after=stage)
        assert _database_fingerprint(_core.read_colmap_db(str(path))) == before


def test_failed_new_transaction_removes_created_database(tmp_path):
    path = tmp_path / "never-partial.db"
    with pytest.raises(RuntimeError, match="injected failure"):
        _core.write_colmap_db(
            _database(), str(path), _test_fail_after=2
        )
    assert not path.exists()


def test_writer_guard_failure_does_not_modify_existing_file(tmp_path):
    path = tmp_path / "guard.db"
    sceneio.write(_database(), path)
    before = hashlib.sha256(path.read_bytes()).digest()
    scored = _core.feature_set(
        np.zeros((1, 2), np.float32),
        np.zeros((1, 4), np.uint8),
        np.ones(1, np.float32),
        image_id=2,
        image_name="a",
        camera_id=5,
        image_size=(640, 480),
        extractor_type=0,
    )
    empty_graph = _core.match_graph(
        np.empty((0, 2), np.uint32),
        np.array([0], np.uint64),
        np.empty((0, 2), np.uint32),
        np.array([0], np.uint64),
        np.empty((0, 2), np.uint32),
    )
    with pytest.raises(sceneio.FormatError, match="scores"):
        sceneio.write(_database(features=[scored], graph=empty_graph), path)
    assert hashlib.sha256(path.read_bytes()).digest() == before


def test_writer_rejects_float_descriptors(tmp_path):
    feature = _core.feature_set(
        np.zeros((1, 2), np.float32),
        np.zeros((1, 4), np.float32),
        image_id=2,
        image_name="a",
        camera_id=5,
        image_size=(640, 480),
        extractor_type=0,
    )
    empty_graph = _core.match_graph(
        np.empty((0, 2), np.uint32),
        np.array([0], np.uint64),
        np.empty((0, 2), np.uint32),
        np.array([0], np.uint64),
        np.empty((0, 2), np.uint32),
    )
    with pytest.raises(sceneio.FormatError, match="must be uint8"):
        sceneio.write(
            _database(features=[feature], graph=empty_graph),
            tmp_path / "float.db",
        )


def test_malformed_blob_extent_rejected_before_bulk_allocation(tmp_path):
    path = tmp_path / "oversized.db"
    sceneio.write(_database(), path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE keypoints SET rows=100000000, cols=6, data=x'00' WHERE image_id=2"
        )
    with pytest.raises(sceneio.FormatError, match="1,000,000,000-byte bound"):
        sceneio.read(path)


@pytest.mark.parametrize("kind", ["missing_table", "truncated"])
def test_read_exception_releases_database_handle_on_windows(tmp_path, kind):
    path = tmp_path / f"{kind}.db"
    if kind == "missing_table":
        connection = sqlite3.connect(path)
        try:
            connection.execute("CREATE TABLE cameras(camera_id INTEGER)")
            connection.commit()
        finally:
            connection.close()
    else:
        sceneio.write(_database(), path)
        path.write_bytes(path.read_bytes()[:100])
    with pytest.raises(sceneio.FormatError):
        sceneio.read(path, format="colmap_db")
    renamed = path.with_suffix(".released")
    path.rename(renamed)
    renamed.unlink()


def test_read_only_path_does_not_change_database_bytes_or_create_journal(tmp_path):
    path = tmp_path / "readonly.db"
    sceneio.write(_database(), path)
    before = hashlib.sha256(path.read_bytes()).digest()
    sceneio.read(path)
    sceneio.read_partial(path, image_id=2)
    sceneio.inspect(path)
    assert hashlib.sha256(path.read_bytes()).digest() == before
    assert not path.with_name(path.name + "-journal").exists()
    assert not path.with_name(path.name + "-wal").exists()


@pytest.mark.skipif(
    os.name == "nt",
    reason="colon and question mark are not valid Windows filename characters",
)
def test_sqlite_uri_spelling_is_treated_as_a_literal_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = Path("file:literal.db?mode=memory")
    sceneio.write(_database(), path, format="colmap_db")
    assert path.is_file()
    assert _database_fingerprint(sceneio.read(path)) == _database_fingerprint(
        _database()
    )


def test_decoded_arrays_outlive_closed_and_removed_database(tmp_path):
    path = tmp_path / "owned.db"
    sceneio.write(_database(), path)
    value = sceneio.read(path)
    keypoints = value.feature(2).keypoints
    matches = value.match_graph.matches
    expected_keypoints = keypoints.copy()
    expected_matches = matches.copy()
    del value
    gc.collect()
    path.unlink()
    np.testing.assert_array_equal(keypoints, expected_keypoints)
    np.testing.assert_array_equal(matches, expected_matches)


def test_wal_writer_exposes_only_the_last_committed_snapshot(tmp_path):
    path = tmp_path / "snapshot.db"
    sceneio.write(_database(), path)
    connection = sqlite3.connect(path)
    try:
        mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()
        assert mode == ("wal",)
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            "UPDATE images SET name='uncommitted.jpg' WHERE image_id=2"
        )
        assert cursor.rowcount == 1
        own_value = connection.execute(
            "SELECT name FROM images WHERE image_id=2"
        ).fetchone()
        assert own_value == ("uncommitted.jpg",)
        assert sceneio.read(path).feature(2).image_name == "a.jpg"
        assert sceneio.read_partial(path, image_id=2).image_name == "a.jpg"
        info = sceneio.inspect(path)
        assert info.count == 2
        assert info.metadata["image_names"] == ("a.jpg", "b.jpg")
    finally:
        connection.rollback()
        connection.close()
    verification = sqlite3.connect(path)
    try:
        rolled_back = verification.execute(
            "SELECT name FROM images WHERE image_id=2"
        ).fetchone()
        assert rolled_back == ("a.jpg",)
    finally:
        verification.close()
    assert sceneio.read(path).feature(2).image_name == "a.jpg"


def test_cross_process_exclusive_lock_fails_cleanly_then_releases(tmp_path):
    path = tmp_path / "locked.db"
    sceneio.write(_database(), path)
    connection = sqlite3.connect(path)
    try:
        mode = connection.execute("PRAGMA journal_mode=DELETE").fetchone()
        assert mode == ("delete",)
    finally:
        connection.close()

    ready = tmp_path / "lock-ready"
    release = tmp_path / "lock-release"
    holder_script = """
import sqlite3
import sys
import time
from pathlib import Path

database = Path(sys.argv[1])
ready = Path(sys.argv[2])
release = Path(sys.argv[3])
connection = sqlite3.connect(database)
try:
    connection.execute("BEGIN EXCLUSIVE")
    connection.execute(
        "UPDATE cameras SET prior_focal_length=0 WHERE camera_id=5"
    )
    ready.write_text("locked", encoding="ascii")
    deadline = time.monotonic() + 30
    while not release.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not release.exists():
        raise RuntimeError("parent did not release the SQLite lock")
    connection.rollback()
finally:
    connection.close()
"""
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            holder_script,
            str(path),
            str(ready),
            str(release),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        while not ready.exists() and time.monotonic() < deadline:
            if holder.poll() is not None:
                _stdout, stderr = holder.communicate()
                pytest.fail(f"SQLite lock holder exited early: {stderr}")
            time.sleep(0.01)
        assert ready.is_file(), "SQLite lock holder did not become ready"

        with pytest.raises(sceneio.FormatError, match="locked"):
            sceneio.read(path)
        with pytest.raises(sceneio.FormatError, match="locked"):
            sceneio.read_partial(path, image_id=2)
        with pytest.raises(sceneio.FormatError, match="locked"):
            sceneio.inspect(path)
    finally:
        release.write_text("release", encoding="ascii")
        try:
            stdout, stderr = holder.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            holder.kill()
            stdout, stderr = holder.communicate()
            pytest.fail(
                "SQLite lock holder did not release: "
                f"stdout={stdout!r}, stderr={stderr!r}"
            )
    assert holder.returncode == 0, stderr
    assert _database_fingerprint(sceneio.read(path)) == _database_fingerprint(
        _database()
    )


def test_nonempty_unrepresented_table_is_rejected_and_handle_released(tmp_path):
    path = tmp_path / "rig.db"
    sceneio.write(_database(), path)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO rigs(rig_id,ref_sensor_id,ref_sensor_type) VALUES(1,1,0)"
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(sceneio.FormatError, match="non-empty 'rigs'"):
        sceneio.read(path)
    os.replace(path, tmp_path / "moved.db")


def test_unknown_table_and_column_are_rejected_instead_of_dropped(tmp_path):
    table_path = tmp_path / "unknown-table.db"
    sceneio.write(_database(), table_path)
    connection = sqlite3.connect(table_path)
    try:
        connection.execute("CREATE TABLE application_payload(value BLOB)")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(sceneio.FormatError, match="unsupported table"):
        sceneio.read(table_path)

    column_path = tmp_path / "unknown-column.db"
    sceneio.write(_database(), column_path)
    connection = sqlite3.connect(column_path)
    try:
        connection.execute("ALTER TABLE images ADD COLUMN opaque BLOB")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(sceneio.FormatError, match=r"images\.opaque"):
        sceneio.read(column_path)


def test_missing_partial_ids_and_invalid_public_pair(tmp_path):
    path = tmp_path / "partial-errors.db"
    sceneio.write(_database(), path)
    with pytest.raises(sceneio.FormatError, match="was not found"):
        sceneio.read_partial(path, image_id=99)
    with pytest.raises(sceneio.FormatError, match="was not found"):
        sceneio.read_partial(path, pair=(2, 99))
    with pytest.raises(ValueError, match="distinct"):
        sceneio.read_partial(path, pair=(2, 2))
    with pytest.raises(ValueError, match=r"0\.\.2147483646"):
        sceneio.read_partial(path, pair=(-1, 2))


@pytest.mark.parametrize(
    ("table", "columns", "message"),
    [
        (
            "images",
            "image_id INTEGER,name TEXT,camera_id INTEGER,time_id INTEGER",
            "duplicate image_id",
        ),
        (
            "keypoints",
            "image_id INTEGER,rows INTEGER,cols INTEGER,data BLOB",
            "duplicate keypoint row",
        ),
        (
            "descriptors",
            "image_id INTEGER,type INTEGER,rows INTEGER,cols INTEGER,data BLOB",
            "duplicate descriptor row",
        ),
    ],
)
def test_partial_image_rejects_duplicate_target_rows(
    tmp_path, table, columns, message
):
    path = tmp_path / f"duplicate-{table}.db"
    sceneio.write(_database(), path)
    connection = sqlite3.connect(path)
    try:
        original = f"original_{table}"
        connection.execute(f"ALTER TABLE {table} RENAME TO {original}")
        connection.execute(f"CREATE TABLE {table}({columns})")
        column_names = ",".join(
            definition.split()[0] for definition in columns.split(",")
        )
        connection.execute(
            f"INSERT INTO {table}({column_names}) "
            f"SELECT {column_names} FROM {original}"
        )
        connection.execute(
            f"INSERT INTO {table}({column_names}) "
            f"SELECT {column_names} FROM {original} WHERE image_id=2"
        )
        connection.execute(f"DROP TABLE {original}")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.read_partial(path, image_id=2)


@pytest.mark.parametrize("malformation", ["bad_index", "missing_endpoint"])
def test_partial_pair_validates_endpoint_rows(tmp_path, malformation):
    path = tmp_path / f"{malformation}.db"
    sceneio.write(_database(), path)
    connection = sqlite3.connect(path)
    try:
        if malformation == "bad_index":
            connection.execute(
                "UPDATE matches SET rows=1,data=?",
                (np.array([[99, 0]], np.uint32).tobytes(),),
            )
        else:
            connection.execute("DELETE FROM images WHERE image_id=11")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(
        sceneio.FormatError,
        match=r"index exceeds|exactly one image",
    ):
        sceneio.read_partial(path, pair=(2, 11))


def test_database_magic_detection_without_extension(tmp_path):
    path = tmp_path / "database"
    sceneio.write(_database(), path, format="colmap_db")
    assert sceneio.detect(path) == "colmap_db"


def test_unicode_path_can_be_created_and_transactionally_replaced(tmp_path):
    path = tmp_path / "特征-база.db"
    expected = _database()
    sceneio.write(expected, path)
    sceneio.write(expected, path)
    assert _database_fingerprint(sceneio.read(path)) == _database_fingerprint(
        expected
    )


def test_randomized_sparse_ids_ragged_matches_and_optional_geometry(tmp_path):
    path = tmp_path / "random.db"
    for seed in range(20):
        rng = np.random.default_rng(seed)
        image_ids = sorted(
            int(value)
            for value in rng.choice(
                np.arange(1, 5000, dtype=np.uint32),
                size=4,
                replace=False,
            )
        )
        camera = _core.camera(
            19,
            1,
            64,
            48,
            np.array([50.0, 51.0, 32.0, 24.0], np.float64),
        )
        features = []
        row_counts = {}
        for index, image_id in enumerate(image_ids):
            rows = int(rng.integers(1, 8))
            row_counts[image_id] = rows
            layout = int(rng.choice([2, 4, 6]))
            features.append(
                _core.feature_set(
                    rng.normal(size=(rows, layout)).astype(np.float32),
                    rng.integers(0, 256, (rows, 16), dtype=np.uint8),
                    image_id=image_id,
                    image_name=f"{seed}/{index}.jpg",
                    camera_id=19,
                    image_size=(64, 48),
                    extractor_type=int(rng.integers(-1, 4)),
                )
            )

        image_pairs = np.array(
            [
                [image_ids[0], image_ids[1]],
                [image_ids[0], image_ids[3]],
                [image_ids[2], image_ids[3]],
            ],
            np.uint32,
        )
        raw_values = []
        verified_values = []
        raw_offsets = [0]
        verified_offsets = [0]
        match_present = []
        geometry_present = []
        for image_a, image_b in image_pairs:
            raw_count = int(rng.integers(0, 6))
            verified_count = int(rng.integers(0, 4))
            raw_values.extend(
                zip(
                    rng.integers(0, row_counts[int(image_a)], raw_count),
                    rng.integers(0, row_counts[int(image_b)], raw_count),
                    strict=True,
                )
            )
            verified_values.extend(
                zip(
                    rng.integers(0, row_counts[int(image_a)], verified_count),
                    rng.integers(0, row_counts[int(image_b)], verified_count),
                    strict=True,
                )
            )
            raw_offsets.append(len(raw_values))
            verified_offsets.append(len(verified_values))
            raw_row = bool(rng.integers(0, 2))
            geometry_row = bool(rng.integers(0, 2))
            if not raw_row and not geometry_row:
                raw_row = True
            if not raw_row and raw_count:
                raw_row = True
            if not geometry_row and verified_count:
                geometry_row = True
            match_present.append(raw_row)
            geometry_present.append(geometry_row)
        pair_count = len(image_pairs)
        geometry_flags = np.asarray(geometry_present, np.uint8)
        matrix_flags = (
            geometry_flags
            * rng.integers(0, 2, pair_count, dtype=np.uint8)
        )
        graph = _core.match_graph(
            image_pairs,
            np.asarray(raw_offsets, np.uint64),
            np.asarray(raw_values, np.uint32).reshape(-1, 2),
            np.asarray(verified_offsets, np.uint64),
            np.asarray(verified_values, np.uint32).reshape(-1, 2),
            configs=np.where(geometry_flags, 2, 0).astype(np.int32),
            fundamental_matrices=rng.normal(size=(pair_count, 3, 3)),
            fundamental_present=matrix_flags,
            essential_matrices=rng.normal(size=(pair_count, 3, 3)),
            essential_present=matrix_flags,
            homographies=rng.normal(size=(pair_count, 3, 3)),
            homography_present=matrix_flags,
            qvecs=np.tile(
                np.array([[1.0, 0, 0, 0]], np.float64),
                (pair_count, 1),
            ),
            tvecs=rng.normal(size=(pair_count, 3)),
            pose_present=geometry_flags,
            match_present=np.asarray(match_present, np.uint8),
            geometry_present=geometry_flags,
        )
        expected = _core.colmap_database(
            [camera],
            features,
            graph,
            prior_focal_length=np.array([seed % 2], np.uint8),
            user_version=4_010_100,
        )
        sceneio.write(expected, path)
        actual = sceneio.read(path)
        assert _database_fingerprint(actual) == _database_fingerprint(expected)
