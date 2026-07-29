"""COLMAP SQLite database record, oracle, partial-read, and failure tests."""

from __future__ import annotations

import gc
import hashlib
import json
import os
import sqlite3
import struct
import subprocess
import sys
import time
import tracemalloc
from contextlib import closing
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


# Frozen from colmap_mod
# de15b08a2dba98b55d6ddfb7cedac147838afbb4
# src/colmap/scene/database_sqlite.cc Create*Table/InitializeOwnership.
# Keep this literal independent of SceneIO's schema generator: these fixtures
# are the decoder-side wire oracle, not a round-trip through the implementation
# under test.
_MAXX_DE15_DDL = """
CREATE TABLE maxx_schema_info(
    schema_version INTEGER PRIMARY KEY NOT NULL,
    minimum_reader_version INTEGER NOT NULL,
    producer_version TEXT NOT NULL,
    producer_commit TEXT NOT NULL);
CREATE TABLE rigs(
    rig_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    ref_sensor_id INTEGER NOT NULL,
    ref_sensor_type INTEGER NOT NULL);
CREATE UNIQUE INDEX rig_ref_sensor_assignment
    ON rigs(ref_sensor_id, ref_sensor_type);
CREATE TABLE rig_sensors(
    rig_id INTEGER NOT NULL,
    sensor_id INTEGER NOT NULL,
    sensor_type INTEGER NOT NULL,
    sensor_from_rig BLOB,
    FOREIGN KEY(rig_id) REFERENCES rigs(rig_id) ON DELETE CASCADE);
CREATE UNIQUE INDEX rig_sensor_assignment
    ON rig_sensors(sensor_id, sensor_type);
CREATE TABLE cameras(
    camera_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    model INTEGER NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    params BLOB,
    prior_focal_length INTEGER NOT NULL);
CREATE TABLE frames(
    frame_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    rig_id INTEGER NOT NULL,
    FOREIGN KEY(rig_id) REFERENCES rigs(rig_id) ON DELETE CASCADE);
CREATE TABLE frame_data(
    frame_id INTEGER NOT NULL,
    data_id INTEGER NOT NULL,
    sensor_id INTEGER NOT NULL,
    sensor_type INTEGER NOT NULL,
    FOREIGN KEY(frame_id) REFERENCES frames(frame_id) ON DELETE CASCADE);
CREATE UNIQUE INDEX frame_sensor_assignment
    ON frame_data(data_id, sensor_type);
CREATE TABLE images(
    image_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    name TEXT NOT NULL UNIQUE,
    camera_id INTEGER NOT NULL,
    time_id INTEGER NULL,
    CONSTRAINT image_id_check
        CHECK(image_id >= 0 AND image_id < 2147483647),
    FOREIGN KEY(camera_id) REFERENCES cameras(camera_id));
CREATE UNIQUE INDEX index_name ON images(name);
CREATE TABLE videos(
    video_id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    name TEXT NOT NULL UNIQUE,
    source_path TEXT,
    content_hash TEXT,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    num_frames INTEGER NOT NULL,
    fps REAL NOT NULL,
    duration_seconds REAL NOT NULL,
    codec_name TEXT,
    sync_group TEXT);
CREATE UNIQUE INDEX index_video_name ON videos(name);
CREATE TABLE video_frames(
    video_id INTEGER NOT NULL,
    image_id INTEGER NOT NULL UNIQUE,
    frame_id INTEGER NOT NULL,
    pts_seconds REAL,
    time_id INTEGER,
    PRIMARY KEY(video_id, frame_id),
    FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE,
    FOREIGN KEY(image_id) REFERENCES images(image_id) ON DELETE CASCADE);
CREATE INDEX index_video_frame_image ON video_frames(image_id);
CREATE TABLE pose_priors(
    pose_prior_id INTEGER PRIMARY KEY NOT NULL,
    corr_data_id INTEGER NOT NULL,
    corr_sensor_id INTEGER NOT NULL,
    corr_sensor_type INTEGER NOT NULL,
    position BLOB,
    position_covariance BLOB,
    gravity BLOB,
    coordinate_system INTEGER NOT NULL,
    rotation BLOB,
    rotation_covariance BLOB,
    pose_covariance BLOB);
CREATE UNIQUE INDEX pose_prior_data_assignment
    ON pose_priors(corr_data_id, corr_sensor_id, corr_sensor_type);
CREATE TABLE image_qualities(
    image_id INTEGER PRIMARY KEY NOT NULL,
    quality REAL NOT NULL,
    FOREIGN KEY(image_id) REFERENCES images(image_id) ON DELETE CASCADE);
CREATE TABLE pair_provenance(
    pair_id INTEGER PRIMARY KEY NOT NULL,
    source_flags INTEGER NOT NULL,
    retrieval_score REAL);
CREATE TABLE markers(
    marker_id INTEGER PRIMARY KEY NOT NULL,
    label TEXT NOT NULL,
    type INTEGER NOT NULL,
    world_position BLOB,
    world_position_cov BLOB,
    point3D_id INTEGER NOT NULL,
    enabled INTEGER NOT NULL);
CREATE UNIQUE INDEX index_marker_label ON markers(label);
CREATE TABLE marker_projections(
    marker_id INTEGER NOT NULL,
    image_id INTEGER NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    size REAL NOT NULL,
    pinned INTEGER NOT NULL,
    point2D_idx INTEGER NOT NULL DEFAULT 4294967295,
    PRIMARY KEY(marker_id, image_id),
    FOREIGN KEY(marker_id) REFERENCES markers(marker_id) ON DELETE CASCADE,
    FOREIGN KEY(image_id) REFERENCES images(image_id) ON DELETE CASCADE);
CREATE INDEX index_marker_projection_image
    ON marker_projections(image_id);
CREATE TABLE keypoints(
    image_id INTEGER PRIMARY KEY NOT NULL,
    rows INTEGER NOT NULL,
    cols INTEGER NOT NULL,
    data BLOB,
    FOREIGN KEY(image_id) REFERENCES images(image_id) ON DELETE CASCADE);
CREATE TABLE keypoint_colors(
    image_id INTEGER PRIMARY KEY NOT NULL,
    rows INTEGER NOT NULL,
    cols INTEGER NOT NULL,
    data BLOB,
    FOREIGN KEY(image_id) REFERENCES keypoints(image_id) ON DELETE CASCADE);
CREATE TABLE descriptors(
    image_id INTEGER PRIMARY KEY NOT NULL,
    type INTEGER NOT NULL,
    type_name TEXT,
    dtype INTEGER,
    dim INTEGER,
    rows INTEGER NOT NULL,
    cols INTEGER NOT NULL,
    data BLOB,
    FOREIGN KEY(image_id) REFERENCES images(image_id) ON DELETE CASCADE);
CREATE TABLE matches(
    pair_id INTEGER PRIMARY KEY NOT NULL,
    rows INTEGER NOT NULL,
    cols INTEGER NOT NULL,
    data BLOB);
CREATE TABLE match_scores(
    pair_id INTEGER PRIMARY KEY NOT NULL,
    rows INTEGER NOT NULL,
    cols INTEGER NOT NULL,
    data BLOB,
    FOREIGN KEY(pair_id) REFERENCES matches(pair_id) ON DELETE CASCADE);
CREATE TABLE two_view_geometries(
    pair_id INTEGER PRIMARY KEY NOT NULL,
    rows INTEGER NOT NULL,
    cols INTEGER NOT NULL,
    data BLOB,
    config INTEGER NOT NULL,
    F BLOB,
    E BLOB,
    H BLOB,
    qvec BLOB,
    tvec BLOB,
    camera1 BLOB,
    camera2 BLOB);
"""


def _empty_maxx_de15_database(path: Path, *, ownership: bool = True) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_MAXX_DE15_DDL)
        connection.execute("PRAGMA application_id=1296128088")
        connection.execute("PRAGMA user_version=3140003")
        if ownership:
            connection.execute(
                "INSERT INTO maxx_schema_info VALUES(1,1,?,?)",
                (
                    "3.14.0",
                    "de15b08a2dba98b55d6ddfb7cedac147838afbb4",
                ),
            )
        else:
            connection.execute("DROP TABLE maxx_schema_info")
            connection.execute("PRAGMA application_id=0")
        connection.commit()
    finally:
        connection.close()


def _empty_profile_database(path: Path, profile_name: str) -> None:
    profile = db_contract.COLMAP_DATABASE_PROFILES_BY_NAME[profile_name]
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_core._colmap_db_profile_schema(profile_name))
        connection.execute(f"PRAGMA application_id={profile.application_id}")
        connection.execute(f"PRAGMA user_version={profile.user_version}")
        if profile.ownership_row:
            connection.execute(
                "INSERT INTO maxx_schema_info VALUES(1,1,?,?)",
                ("3.14.0", profile.source_revision),
            )
        connection.commit()
    finally:
        connection.close()


def _recovered_camera_blob(
    *,
    camera_id: int = 23,
    model_id: int = 1,
    width: int = 640,
    height: int = 480,
    prior_focal_length: int = 1,
    params: tuple[float, ...] = (500.0, 501.0, 320.0, 240.0),
) -> bytes:
    return struct.pack(
        "<IiQQBQ",
        camera_id,
        model_id,
        width,
        height,
        prior_focal_length,
        len(params),
    ) + struct.pack(f"<{len(params)}d", *params)


def _current_recovered_camera_database(
    path: Path,
    *,
    camera1: object = ...,
    camera2: object = None,
) -> None:
    _current_recovered_camera_pairs_database(
        path, [(2, 11, camera1, camera2)]
    )


def _current_recovered_camera_pairs_database(
    path: Path,
    rows: list[tuple[int, int, object, object]],
) -> None:
    _empty_profile_database(path, "colmap-main-64805cb870b5")
    rows = [
        (
            image_id1,
            image_id2,
            _recovered_camera_blob() if camera1 is ... else camera1,
            camera2,
        )
        for image_id1, image_id2, camera1, camera2 in rows
    ]
    image_ids = sorted(
        {
            image_id
            for image_id1, image_id2, _camera1, _camera2 in rows
            for image_id in (image_id1, image_id2)
        }
    )
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO cameras"
            "(camera_id,model,width,height,params,prior_focal_length) "
            "VALUES(5,1,640,480,?,1)",
            (np.array([500.0, 501.0, 320.0, 240.0], np.float64).tobytes(),),
        )
        connection.executemany(
            "INSERT INTO images(image_id,name,camera_id) VALUES(?,?,5)",
            [(image_id, f"{image_id}.jpg") for image_id in image_ids],
        )
        connection.executemany(
            "INSERT INTO two_view_geometries"
            "(pair_id,rows,cols,data,config,F,E,H,qvec,tvec,camera1,camera2) "
            "VALUES(?,0,2,?,0,NULL,NULL,NULL,NULL,NULL,?,?)",
            [
                (
                    min(image_id1, image_id2) * 2_147_483_647
                    + max(image_id1, image_id2),
                    b"",
                    camera1,
                    camera2,
                )
                for image_id1, image_id2, camera1, camera2 in rows
            ],
        )
        connection.commit()
    finally:
        connection.close()


_PRIOR_POSITION = np.array([1.25, -0.0, 3.5], np.float64)
_PRIOR_COVARIANCE = np.array(
    [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 10.0]],
    np.float64,
)
_RIG_SENSOR_POSE = (1.0, -0.0, 0.0, 0.0, 1.0, -2.0, 3.0)
_NAN_PAYLOAD_BITS = np.array(
    [0x7FF8000000000042, 0xFFF8000000000011, 0x7FF0000000000001],
    np.uint64,
)


def _stock_companion_database(path: Path, profile_name: str) -> None:
    """Build exact stock rig/frame/prior rows with stdlib wire payloads."""
    assert profile_name in {
        "colmap-3.13.0",
        "colmap-4.1.1",
        "colmap-main-64805cb870b5",
    }
    _empty_profile_database(path, profile_name)
    camera_params = struct.pack("<3d", 500.0, 320.0, 240.0)
    covariance_column_major = _PRIOR_COVARIANCE.T.copy().tobytes()
    connection = sqlite3.connect(path)
    try:
        connection.executemany(
            "INSERT INTO cameras"
            "(camera_id,model,width,height,params,prior_focal_length) "
            "VALUES(?,0,640,480,?,?)",
            [(5, camera_params, 1), (6, camera_params, 0)],
        )
        connection.executemany(
            "INSERT INTO images(image_id,name,camera_id) VALUES(?,?,?)",
            [(2, "2.jpg", 5), (11, "11.jpg", 6)],
        )
        connection.executemany(
            "INSERT INTO rigs(rig_id,ref_sensor_id,ref_sensor_type) "
            "VALUES(?,?,?)",
            [(3, 5, 0), (40, 9, 1)],
        )
        connection.executemany(
            "INSERT INTO rig_sensors"
            "(rig_id,sensor_id,sensor_type,sensor_from_rig) VALUES(?,?,?,?)",
            [
                (3, 8, 1, struct.pack("<7d", *_RIG_SENSOR_POSE)),
                (40, 6, 0, None),
            ],
        )
        connection.executemany(
            "INSERT INTO frames(frame_id,rig_id) VALUES(?,?)",
            [(7, 3), (21, 40), (99, 3)],
        )
        connection.executemany(
            "INSERT INTO frame_data"
            "(frame_id,data_id,sensor_id,sensor_type) VALUES(?,?,?,?)",
            [(7, 2, 5, 0), (7, 100, 8, 1), (21, 11, 6, 0)],
        )
        if profile_name == "colmap-3.13.0":
            connection.executemany(
                "INSERT INTO pose_priors"
                "(image_id,position,coordinate_system,position_covariance) "
                "VALUES(?,?,?,?)",
                [
                    (
                        2,
                        _PRIOR_POSITION.tobytes(),
                        0,
                        covariance_column_major,
                    ),
                    (11, None, -1, None),
                ],
            )
        else:
            connection.executemany(
                "INSERT INTO pose_priors"
                "(pose_prior_id,corr_data_id,corr_sensor_id,corr_sensor_type,"
                "position,position_covariance,gravity,coordinate_system) "
                "VALUES(?,?,?,?,?,?,?,?)",
                [
                    (
                        71,
                        2,
                        5,
                        0,
                        _PRIOR_POSITION.tobytes(),
                        covariance_column_major,
                        None,
                        1,
                    ),
                    (
                        99,
                        777,
                        123,
                        1,
                        _NAN_PAYLOAD_BITS.tobytes(),
                        None,
                        np.array([0.0, -0.0, 1.0], np.float64).tobytes(),
                        -1,
                    ),
                ],
            )
        connection.commit()
    finally:
        connection.close()


def _maxx_extension_database(path: Path) -> dict[str, object]:
    """Build MAXX extension rows independently with sqlite3 and wire bytes."""
    _empty_maxx_de15_database(path)
    descriptors = (
        np.array([[0, 255], [17, 33]], np.uint8),
        np.array([[-128, 127], [-3, 4]], np.int8),
        np.array([[0x7E42, 0x8000], [0x3C00, 0xFC00]], np.uint16).view(
            np.float16
        ),
        np.array([[np.nan, -0.0], [np.inf, -np.inf]], np.float32),
        np.array([[np.nan, -0.0], [np.inf, -np.inf]], np.float64),
    )
    pair_id = 1 * 2_147_483_647 + 2
    provenance_only_pair_id = 100 * 2_147_483_647 + 101
    rotation = np.array([0.1, -0.2, 0.3, 0.9], np.float64)
    rotation_covariance = np.arange(1, 10, dtype=np.float64).reshape(3, 3)
    pose_covariance = np.arange(1, 37, dtype=np.float64).reshape(6, 6)
    marker_position = np.array(
        [0x7FF8000000000042, 0x8000000000000000, 0x3FF0000000000000],
        np.uint64,
    ).view(np.float64)
    marker_covariance = np.arange(10, 19, dtype=np.float64).reshape(3, 3)
    match_scores = np.array(
        [0x7FC00042, 0xFF800000], np.uint32
    ).view(np.float32)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO cameras"
            "(camera_id,model,width,height,params,prior_focal_length) "
            "VALUES(7,0,640,480,?,1)",
            (struct.pack("<3d", 500.0, 320.0, 240.0),),
        )
        connection.executemany(
            "INSERT INTO images(image_id,name,camera_id,time_id) "
            "VALUES(?,?,7,?)",
            [
                (image_id, f"{image_id}.jpg", 17 if image_id == 1 else None)
                for image_id in range(1, 6)
            ],
        )
        keypoints = np.array([[1.5, 2.5], [3.5, 4.5]], np.float32)
        connection.executemany(
            "INSERT INTO keypoints(image_id,rows,cols,data) "
            "VALUES(?,2,2,?)",
            [(image_id, keypoints.tobytes()) for image_id in range(1, 6)],
        )
        connection.executemany(
            "INSERT INTO descriptors"
            "(image_id,type,type_name,dtype,dim,rows,cols,data) "
            "VALUES(?,?,?,?,?,2,?,?)",
            [
                (
                    image_id,
                    (0, -1, -1, 1, -1)[image_id - 1],
                    "" if image_id == 1 else None,
                    image_id - 1,
                    2,
                    value.shape[1] * value.dtype.itemsize,
                    value.tobytes(),
                )
                for image_id, value in enumerate(descriptors, 1)
            ],
        )
        colors = np.array([[1, 2, 3], [250, 251, 252]], np.uint8)
        connection.execute(
            "INSERT INTO keypoint_colors(image_id,rows,cols,data) "
            "VALUES(1,2,3,?)",
            (colors.tobytes(),),
        )
        connection.execute(
            "INSERT INTO image_qualities(image_id,quality) VALUES(1,?)",
            (-0.0,),
        )
        matches = np.array([[0, 1], [1, 0]], np.uint32)
        connection.execute(
            "INSERT INTO matches(pair_id,rows,cols,data) VALUES(?,2,2,?)",
            (pair_id, matches.tobytes()),
        )
        connection.execute(
            "INSERT INTO match_scores(pair_id,rows,cols,data) "
            "VALUES(?,2,1,?)",
            (pair_id, match_scores.tobytes()),
        )
        connection.executemany(
            "INSERT INTO pair_provenance"
            "(pair_id,source_flags,retrieval_score) VALUES(?,?,?)",
            [
                (pair_id, 0x80000001, float("inf")),
                (provenance_only_pair_id, 0, None),
            ],
        )
        connection.execute(
            "INSERT INTO pose_priors"
            "(pose_prior_id,corr_data_id,corr_sensor_id,corr_sensor_type,"
            "position,position_covariance,gravity,coordinate_system,"
            "rotation,rotation_covariance,pose_covariance) "
            "VALUES(71,1,7,0,NULL,NULL,NULL,-1,?,?,?)",
            (
                rotation.tobytes(),
                rotation_covariance.T.copy().tobytes(),
                pose_covariance.T.copy().tobytes(),
            ),
        )
        connection.executemany(
            "INSERT INTO markers"
            "(marker_id,label,type,world_position,world_position_cov,"
            "point3D_id,enabled) VALUES(?,?,?,?,?,?,?)",
            [
                (
                    9,
                    "origin",
                    2,
                    marker_position.tobytes(),
                    marker_covariance.T.copy().tobytes(),
                    -1,
                    1,
                ),
                (10, "unset", 0, None, None, 123, 0),
            ],
        )
        connection.execute(
            "INSERT INTO marker_projections"
            "(marker_id,image_id,x,y,size,pinned,point2D_idx) "
            "VALUES(9,1,?,20.25,-3.5,1,4294967295)",
            (float("inf"),),
        )
        connection.executemany(
            "INSERT INTO videos"
            "(video_id,name,source_path,content_hash,width,height,"
            "num_frames,fps,duration_seconds,codec_name,sync_group) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [
                (3, "capture", "", None, 640, 480, 99, 30.0, 3.3, "raw", ""),
                (4, "other", None, "", -1, 0, -5, float("inf"), -0.0, None, None),
            ],
        )
        connection.execute(
            "INSERT INTO video_frames"
            "(video_id,image_id,frame_id,pts_seconds,time_id) "
            "VALUES(3,1,8,?,19)",
            (float("inf"),),
        )
    connection.close()
    return {
        "descriptors": descriptors,
        "colors": colors,
        "pair_id": pair_id,
        "provenance_only_pair_id": provenance_only_pair_id,
        "rotation": rotation,
        "rotation_covariance": rotation_covariance,
        "pose_covariance": pose_covariance,
        "marker_position": marker_position,
        "marker_covariance": marker_covariance,
        "match_scores": match_scores,
    }


def _maxx_single_surface_database(path: Path, surface: str) -> None:
    _empty_maxx_de15_database(
        path, ownership=surface == "ownership"
    )
    pair_id = 1 * 2_147_483_647 + 2
    with sqlite3.connect(path) as connection:
        if surface != "ownership":
            connection.execute(
                "INSERT INTO cameras VALUES(7,0,640,480,?,1)",
                (struct.pack("<3d", 500.0, 320.0, 240.0),),
            )
            connection.executemany(
                "INSERT INTO images VALUES(?,?,7,NULL)",
                ((1, "1.jpg"), (2, "2.jpg")),
            )
        if surface in {"descriptor", "keypoint_colors"}:
            connection.execute(
                "INSERT INTO keypoints VALUES(1,0,2,?)", (b"",)
            )
        if surface == "descriptor":
            connection.execute(
                "INSERT INTO descriptors VALUES"
                "(1,0,'SIFT',0,2,0,2,?)",
                (b"",),
            )
        elif surface == "keypoint_colors":
            connection.execute(
                "INSERT INTO keypoint_colors VALUES(1,0,3,?)",
                (b"",),
            )
        elif surface == "image_quality":
            connection.execute(
                "INSERT INTO image_qualities VALUES(1,?)", (-0.0,)
            )
        elif surface == "match_scores":
            connection.execute(
                "INSERT INTO matches VALUES(?,0,2,?)",
                (pair_id, b""),
            )
            connection.execute(
                "INSERT INTO match_scores VALUES(?,0,1,?)",
                (pair_id, b""),
            )
        elif surface == "pair_provenance":
            connection.execute(
                "INSERT INTO pair_provenance VALUES(?,0,NULL)",
                (pair_id,),
            )
        elif surface == "extended_pose":
            connection.execute(
                "INSERT INTO pose_priors VALUES"
                "(71,1,7,0,NULL,NULL,NULL,-1,?,NULL,NULL)",
                (struct.pack("<4d", 0.0, 0.0, 0.0, 1.0),),
            )
        elif surface == "markers":
            connection.execute(
                "INSERT INTO markers VALUES"
                "(9,'marker',0,NULL,NULL,-1,1)"
            )
        elif surface == "videos":
            connection.execute(
                "INSERT INTO videos VALUES"
                "(3,'video',NULL,NULL,640,480,0,30.0,0.0,NULL,NULL)"
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


@pytest.mark.parametrize(
    "profile_name",
    [
        "colmap-3.13.0",
        "colmap-4.1.1",
        "colmap-main-64805cb870b5",
    ],
)
def test_read_stock_rigs_frames_and_pose_priors_exactly(tmp_path, profile_name):
    path = tmp_path / f"{profile_name}-companions.db"
    _stock_companion_database(path, profile_name)

    database = _core.read_colmap_db(str(path))
    inspection = _core.inspect_colmap_db(str(path))
    public_inspection = sceneio.inspect(path)
    rigs = database.rig_frames
    priors = database.pose_priors

    assert rigs.num_rigs == 2
    assert rigs.num_rig_sensors == 2
    assert rigs.num_frames == 3
    assert rigs.num_frame_data == 3
    assert rigs.rig_ids.dtype == np.uint32
    assert rigs.rig_reference_sensor_types.dtype == np.int32
    assert rigs.rig_sensor_offsets.dtype == np.uint64
    assert rigs.rig_sensor_pose_present.dtype == np.uint8
    assert rigs.rig_sensor_quaternions.dtype == np.float64
    assert rigs.frame_data_ids.dtype == np.uint64
    assert inspection["num_rigs"] == 2
    assert inspection["num_rig_sensors"] == 2
    assert inspection["num_frames"] == 3
    assert inspection["num_frame_data"] == 3
    assert inspection["num_pose_priors"] == 2
    assert inspection["pose_prior_layout"] == (
        "image-linked-3.13"
        if profile_name == "colmap-3.13.0"
        else "correlated-modern"
    )
    assert public_inspection.metadata["num_rigs"] == 2
    assert public_inspection.metadata["num_rig_sensors"] == 2
    assert public_inspection.metadata["num_frames"] == 3
    assert public_inspection.metadata["num_frame_data"] == 3
    assert public_inspection.metadata["num_pose_priors"] == 2
    assert (
        public_inspection.metadata["pose_prior_layout"]
        == inspection["pose_prior_layout"]
    )
    assert rigs.rig_ids.tolist() == [3, 40]
    assert rigs.rig_reference_sensor_types.tolist() == [0, 1]
    assert rigs.rig_reference_sensor_ids.tolist() == [5, 9]
    assert rigs.rig_sensor_offsets.tolist() == [0, 1, 2]
    assert rigs.rig_sensor_types.tolist() == [1, 0]
    assert rigs.rig_sensor_ids.tolist() == [8, 6]
    assert rigs.rig_sensor_pose_present.tolist() == [1, 0]
    assert rigs.quaternion_order == "wxyz"
    assert rigs.sensor_pose_convention == "sensor_from_rig"
    np.testing.assert_array_equal(
        rigs.rig_sensor_quaternions[0].view(np.uint64),
        np.array(_RIG_SENSOR_POSE[:4], np.float64).view(np.uint64),
    )
    np.testing.assert_array_equal(
        rigs.rig_sensor_translations[0].view(np.uint64),
        np.array(_RIG_SENSOR_POSE[4:], np.float64).view(np.uint64),
    )
    np.testing.assert_array_equal(rigs.rig_sensor_quaternions[1], 0.0)
    np.testing.assert_array_equal(rigs.rig_sensor_translations[1], 0.0)
    assert rigs.frame_ids.tolist() == [7, 21, 99]
    assert rigs.frame_rig_ids.tolist() == [3, 40, 3]
    assert rigs.frame_data_offsets.tolist() == [0, 2, 3, 3]
    assert rigs.frame_data_ids.tolist() == [2, 100, 11]
    assert rigs.frame_sensor_types.tolist() == [0, 1, 0]
    assert rigs.frame_sensor_ids.tolist() == [5, 8, 6]

    assert priors.num_pose_priors == 2
    assert priors.prior_ids.dtype == np.uint32
    assert priors.correlated_data_ids.dtype == np.uint64
    assert priors.correlated_sensor_types.dtype == np.int32
    assert priors.position_present.dtype == np.uint8
    assert priors.positions.dtype == np.float64
    if profile_name == "colmap-3.13.0":
        assert not priors.generalized
        assert priors.prior_ids.tolist() == [2, 11]
        assert priors.correlated_data_ids.tolist() == [2, 11]
        assert priors.correlated_sensor_ids.tolist() == [5, 6]
        assert priors.correlated_sensor_types.tolist() == [0, 0]
        assert priors.coordinate_systems.tolist() == [0, -1]
        assert priors.position_present.tolist() == [1, 0]
        assert priors.position_covariance_present.tolist() == [1, 0]
        assert priors.gravity_present.tolist() == [0, 0]
        np.testing.assert_array_equal(priors.positions[1], 0.0)
        np.testing.assert_array_equal(priors.position_covariances[1], 0.0)
        np.testing.assert_array_equal(priors.gravities, 0.0)
    else:
        assert priors.generalized
        assert priors.prior_ids.tolist() == [71, 99]
        assert priors.correlated_data_ids.tolist() == [2, 777]
        assert priors.correlated_sensor_ids.tolist() == [5, 123]
        assert priors.correlated_sensor_types.tolist() == [0, 1]
        assert priors.coordinate_systems.tolist() == [1, -1]
        assert priors.position_present.tolist() == [1, 1]
        assert priors.position_covariance_present.tolist() == [1, 0]
        assert priors.gravity_present.tolist() == [0, 1]
        assert np.isnan(priors.positions[1]).all()
        np.testing.assert_array_equal(
            priors.positions[1].view(np.uint64), _NAN_PAYLOAD_BITS
        )
        np.testing.assert_array_equal(
            priors.gravities[1].view(np.uint64),
            np.array([0.0, -0.0, 1.0], np.float64).view(np.uint64),
        )
        np.testing.assert_array_equal(priors.position_covariances[1], 0.0)
        np.testing.assert_array_equal(priors.gravities[0], 0.0)
    np.testing.assert_array_equal(
        priors.positions[0].view(np.uint64),
        _PRIOR_POSITION.view(np.uint64),
    )
    np.testing.assert_array_equal(
        priors.position_covariances[0], _PRIOR_COVARIANCE
    )


def test_pycolmap_411_producer_rig_frame_and_prior_oracle(tmp_path):
    pycolmap = pytest.importorskip("pycolmap")
    if tuple(int(item) for item in pycolmap.__version__.split(".")[:2]) != (
        4,
        1,
    ):
        pytest.skip("the producer oracle is pinned to pycolmap 4.1.x")
    path = tmp_path / "pycolmap-4.1.1.db"
    producer = pycolmap.Database.open(path)
    rig = pycolmap.Rig()
    rig.rig_id = 3
    rig.add_ref_sensor(
        pycolmap.sensor_t(pycolmap.SensorType.CAMERA, 5)
    )
    rig.add_sensor(
        pycolmap.sensor_t(pycolmap.SensorType.IMU, 8),
        pycolmap.Rigid3d(),
    )
    assert producer.write_rig(rig, True) == 3
    frame = pycolmap.Frame()
    frame.frame_id = 7
    frame.rig_id = 3
    frame.add_data_id(
        pycolmap.data_t(
            pycolmap.sensor_t(pycolmap.SensorType.CAMERA, 5), 2
        )
    )
    assert producer.write_frame(frame, True) == 7
    prior = pycolmap.PosePrior()
    prior.pose_prior_id = 71
    prior.corr_data_id = pycolmap.data_t(
        pycolmap.sensor_t(pycolmap.SensorType.CAMERA, 5), 2
    )
    prior.position = _PRIOR_POSITION.copy()
    prior.coordinate_system = (
        pycolmap.PosePriorCoordinateSystem.CARTESIAN
    )
    assert producer.write_pose_prior(prior, True) == 71
    producer.close()

    connection = sqlite3.connect(path)
    try:
        raw = connection.execute(
            "SELECT typeof(position),length(position),"
            "typeof(position_covariance),length(position_covariance),"
            "typeof(gravity),length(gravity) FROM pose_priors"
        ).fetchone()
    finally:
        connection.close()
    assert raw == ("blob", 24, "blob", 72, "blob", 24)

    database = _core.read_colmap_db(str(path))
    assert database.profile == "colmap-4.1.1"
    assert database.rig_frames.rig_ids.tolist() == [3]
    assert database.rig_frames.frame_ids.tolist() == [7]
    assert database.rig_frames.frame_data_ids.tolist() == [2]
    assert database.pose_priors.position_present.tolist() == [1]
    assert database.pose_priors.position_covariance_present.tolist() == [1]
    assert database.pose_priors.gravity_present.tolist() == [1]
    np.testing.assert_array_equal(
        database.pose_priors.positions[0].view(np.uint64),
        _PRIOR_POSITION.view(np.uint64),
    )
    assert np.isnan(database.pose_priors.position_covariances[0]).all()
    assert np.isnan(database.pose_priors.gravities[0]).all()


def test_exact_de15_pycolmap_database_producer_oracle_when_available(
    tmp_path,
):
    script = (
        "import sys\n"
        "if sys.argv[1]:\n"
        "    sys.path.insert(0, sys.argv[1])\n"
        "import pycolmap\n"
        "database = pycolmap.Database.open(sys.argv[2])\n"
        "database.close()\n"
    )
    compile(script, "<de15-producer-oracle>", "exec")
    producer_python = os.environ.get("SCENEIO_DE15_PYTHON")
    binding_root = os.environ.get("SCENEIO_DE15_PYCOLMAP_PATH")
    if not producer_python and not binding_root:
        pytest.skip(
            "requires SCENEIO_DE15_PYTHON or "
            "SCENEIO_DE15_PYCOLMAP_PATH for a pycolmap build from "
            "de15b08a2dba98b55d6ddfb7cedac147838afbb4"
        )
    interpreter = (
        Path(producer_python) if producer_python else Path(sys.executable)
    )
    if not interpreter.is_file():
        pytest.skip("the configured de15 Python interpreter is unavailable")
    binding_path = Path(binding_root) if binding_root else None
    if binding_path is not None and not binding_path.is_dir():
        pytest.skip(
            "SCENEIO_DE15_PYCOLMAP_PATH is not an available directory"
        )
    path = tmp_path / "de15-producer.db"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            str(interpreter),
            "-c",
            script,
            "" if binding_path is None else str(binding_path),
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode == 0, result.stderr

    with sqlite3.connect(path) as connection:
        application_id = connection.execute(
            "PRAGMA application_id"
        ).fetchone()[0]
        user_version = connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0]
        ownership = connection.execute(
            "SELECT schema_version,minimum_reader_version,"
            "producer_version,producer_commit FROM maxx_schema_info"
        ).fetchall()
    assert application_id == 0x4D415858
    assert user_version == 3_140_003
    assert len(ownership) == 1
    assert ownership[0][0:2] == (1, 1)
    assert len(ownership[0][3]) >= 7
    assert (
        "de15b08a2dba98b55d6ddfb7cedac147838afbb4".startswith(
            ownership[0][3]
        )
    )

    database = _core.read_colmap_db(str(path))
    assert database.profile == "maxx-v1"
    assert database.maxx_schema_info.producer_commit == ownership[0][3]


def test_stock_companion_views_outlive_database_and_file(tmp_path):
    path = tmp_path / "lifetime.db"
    _stock_companion_database(path, "colmap-4.1.1")
    database = _core.read_colmap_db(str(path))
    arrays = (
        database.rig_frames.rig_sensor_quaternions,
        database.rig_frames.frame_data_ids,
        database.pose_priors.positions,
        database.pose_priors.position_covariances,
    )
    expected = tuple(array.copy() for array in arrays)
    del database
    gc.collect()
    path.unlink()

    for actual, wanted in zip(arrays, expected, strict=True):
        np.testing.assert_array_equal(actual, wanted)


def test_prior_covariance_preserves_ieee_bits_across_wire_transpose(tmp_path):
    path = tmp_path / "covariance-bits.db"
    _stock_companion_database(path, "colmap-4.1.1")
    logical_bits = np.array(
        [
            0x7FF8000000000042,
            0x8000000000000000,
            0x3FF0000000000000,
            0xFFF8000000000011,
            0x0000000000000000,
            0x4000000000000000,
            0x7FF0000000000001,
            0xC008000000000000,
            0x4010000000000000,
        ],
        np.uint64,
    ).reshape(3, 3)
    wire = logical_bits.T.copy().tobytes()
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE pose_priors SET position_covariance=? "
            "WHERE pose_prior_id=71",
            (wire,),
        )
        connection.commit()
    finally:
        connection.close()

    covariance = _core.read_colmap_db(
        str(path)
    ).pose_priors.position_covariances[0]
    np.testing.assert_array_equal(covariance.view(np.uint64), logical_bits)


@pytest.mark.parametrize(
    ("sql", "parameters", "message"),
    [
        (
            "UPDATE rig_sensors SET sensor_from_rig=? WHERE rig_id=3",
            (b"",),
            "sensor_from_rig byte count",
        ),
        (
            "UPDATE rig_sensors SET sensor_from_rig=? WHERE rig_id=3",
            (b"\0" * 55,),
            "sensor_from_rig byte count",
        ),
        (
            "UPDATE rig_sensors SET sensor_from_rig=? WHERE rig_id=3",
            (b"\0" * 57,),
            "sensor_from_rig byte count",
        ),
        (
            "UPDATE rig_sensors SET sensor_from_rig=? WHERE rig_id=3",
            (struct.pack("<7d", 2.0, 0.0, 0.0, 0.0, 1.0, 2.0, 3.0),),
            "unit length",
        ),
        (
            "UPDATE rig_sensors SET sensor_from_rig=? WHERE rig_id=3",
            (struct.pack("<7d", np.nan, 0.0, 0.0, 0.0, 1.0, 2.0, 3.0),),
            "quaternion must be finite",
        ),
        (
            "UPDATE rig_sensors SET sensor_from_rig=? WHERE rig_id=3",
            (struct.pack("<7d", 1.0, 0.0, 0.0, 0.0, np.nan, 2.0, 3.0),),
            "translation must be finite",
        ),
        (
            "UPDATE frame_data SET sensor_id=6 WHERE frame_id=7 AND data_id=2",
            (),
            "invalid datum or sensor",
        ),
        (
            "UPDATE rig_sensors SET sensor_id=5,sensor_type=0 "
            "WHERE rig_id=3",
            (),
            "sensor cannot belong to multiple rigs",
        ),
        (
            "UPDATE rig_sensors SET rig_id=777 WHERE rig_id=3",
            (),
            "references a missing rig",
        ),
        (
            "UPDATE frame_data SET frame_id=777 WHERE frame_id=7",
            (),
            "references a missing frame",
        ),
        (
            "UPDATE frames SET rig_id=777 WHERE frame_id=7",
            (),
            "invalid id or rig reference",
        ),
        (
            "UPDATE pose_priors SET position=? WHERE pose_prior_id=71",
            (b"",),
            "position byte count",
        ),
        (
            "UPDATE pose_priors SET position=? WHERE pose_prior_id=71",
            (b"\0" * 23,),
            "position byte count",
        ),
        (
            "UPDATE pose_priors SET position=? WHERE pose_prior_id=71",
            (b"\0" * 25,),
            "position byte count",
        ),
        (
            "UPDATE pose_priors SET position=? WHERE pose_prior_id=71",
            ("not-a-blob",),
            "must be BLOB or NULL",
        ),
        (
            "UPDATE pose_priors SET coordinate_system=2 WHERE pose_prior_id=71",
            (),
            "pose prior metadata is invalid",
        ),
    ],
)
def test_stock_companion_malformed_rows_release_handle(
    tmp_path, sql, parameters, message
):
    path = tmp_path / "malformed-companion.db"
    _stock_companion_database(path, "colmap-4.1.1")
    connection = sqlite3.connect(path)
    try:
        connection.execute(sql, parameters)
        connection.commit()
    finally:
        connection.close()

    inspection = _core.inspect_colmap_db(str(path))
    assert inspection["num_rigs"] == 2
    assert inspection["num_pose_priors"] == 2
    with pytest.raises(ValueError, match=message):
        _core.read_colmap_db(str(path))
    path.rename(path.with_suffix(".released"))


@pytest.mark.parametrize(
    ("quaternion_w", "accepted"),
    [
        (1.0 - 0.5e-6, True),
        (1.0 + 0.5e-6, True),
        (1.0 - 1.1e-6, False),
        (1.0 + 1.1e-6, False),
    ],
)
def test_rig_quaternion_uses_de15_norm_tolerance(
    tmp_path, quaternion_w, accepted
):
    path = tmp_path / "quaternion-tolerance.db"
    _stock_companion_database(path, "colmap-4.1.1")
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE rig_sensors SET sensor_from_rig=? WHERE rig_id=3",
            (
                struct.pack(
                    "<7d", quaternion_w, 0.0, 0.0, 0.0, 1.0, 2.0, 3.0
                ),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    if accepted:
        assert _core.read_colmap_db(
            str(path)
        ).rig_frames.rig_sensor_pose_present.tolist() == [1, 0]
    else:
        with pytest.raises(ValueError, match="unit length"):
            _core.read_colmap_db(str(path))


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (2**32 - 1, "pose prior metadata is invalid"),
        (2**32, "outside uint32"),
    ],
)
def test_stock_companion_rejects_reserved_or_wide_prior_ids(
    tmp_path, value, message
):
    path = tmp_path / "prior-id-boundary.db"
    _stock_companion_database(path, "colmap-4.1.1")
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE pose_priors SET pose_prior_id=71+? "
            "WHERE pose_prior_id=71",
            (value - 71,),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ValueError, match=message):
        _core.read_colmap_db(str(path))


def test_stock_companion_accepts_zero_ids_and_signed_int64_data_ids(tmp_path):
    path = tmp_path / "stock-id-domain.db"
    _empty_profile_database(path, "colmap-4.1.1")
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO rigs(rig_id,ref_sensor_id,ref_sensor_type) "
            "VALUES(0,0,0)"
        )
        connection.execute(
            "INSERT INTO frames(frame_id,rig_id) VALUES(0,0)"
        )
        connection.execute(
            "INSERT INTO frame_data"
            "(frame_id,data_id,sensor_id,sensor_type) VALUES(0,?,0,0)",
            (2**63 - 1,),
        )
        connection.execute(
            "INSERT INTO pose_priors"
            "(pose_prior_id,corr_data_id,corr_sensor_id,corr_sensor_type,"
            "position,position_covariance,gravity,coordinate_system) "
            "VALUES(0,?,0,0,NULL,NULL,NULL,-1)",
            (2**63 - 1,),
        )
        connection.commit()
    finally:
        connection.close()

    database = _core.read_colmap_db(str(path))
    assert database.rig_frames.rig_ids.tolist() == [0]
    assert database.rig_frames.frame_ids.tolist() == [0]
    assert database.rig_frames.rig_reference_sensor_ids.tolist() == [0]
    assert database.rig_frames.frame_data_ids.dtype == np.uint64
    assert database.rig_frames.frame_data_ids.tolist() == [2**63 - 1]
    assert database.pose_priors.prior_ids.tolist() == [0]
    assert database.pose_priors.correlated_sensor_ids.tolist() == [0]
    assert database.pose_priors.correlated_data_ids.dtype == np.uint64
    assert database.pose_priors.correlated_data_ids.tolist() == [2**63 - 1]


@pytest.mark.parametrize(
    ("table", "column", "where", "message"),
    [
        ("frame_data", "data_id", "frame_id=7 AND data_id=2", "frame data_id"),
        (
            "pose_priors",
            "corr_data_id",
            "pose_prior_id=71",
            "pose prior correlated data_id",
        ),
    ],
)
def test_stock_companion_rejects_negative_data_ids(
    tmp_path, table, column, where, message
):
    path = tmp_path / f"negative-{table}-data-id.db"
    _stock_companion_database(path, "colmap-4.1.1")
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            f"UPDATE {table} SET {column}=-1 WHERE {where}"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ValueError, match=rf"{message} must be non-negative"):
        _core.read_colmap_db(str(path))


def test_stock_companion_rejects_partial_table_quartet(tmp_path):
    path = tmp_path / "partial-rig-schema.db"
    _empty_profile_database(path, "colmap-4.1.1")
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TABLE frame_data")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ValueError, match="must be present together"):
        _core.read_colmap_db(str(path))


def test_stock_companion_rejects_incomplete_pose_prior_layout(tmp_path):
    path = tmp_path / "partial-prior-schema.db"
    _empty_profile_database(path, "colmap-4.1.1")
    connection = sqlite3.connect(path)
    try:
        connection.execute("ALTER TABLE pose_priors DROP COLUMN gravity")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ValueError, match="incomplete column layout"):
        _core.read_colmap_db(str(path))


def test_generalized_prior_uniqueness_includes_sensor_id(tmp_path):
    path = tmp_path / "prior-correlation-key.db"
    _stock_companion_database(path, "colmap-4.1.1")
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO pose_priors"
            "(pose_prior_id,corr_data_id,corr_sensor_id,corr_sensor_type,"
            "position,position_covariance,gravity,coordinate_system) "
            "VALUES(100,777,124,1,NULL,NULL,NULL,-1)"
        )
        connection.commit()
    finally:
        connection.close()

    priors = _core.read_colmap_db(str(path)).pose_priors
    assert priors.prior_ids.tolist() == [71, 99, 100]
    assert priors.correlated_data_ids.tolist() == [2, 777, 777]
    assert priors.correlated_sensor_ids.tolist() == [5, 123, 124]


def test_frame_data_allows_same_numeric_id_across_sensor_types(tmp_path):
    path = tmp_path / "frame-data-type-key.db"
    _stock_companion_database(path, "colmap-4.1.1")
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO frame_data"
            "(frame_id,data_id,sensor_id,sensor_type) VALUES(7,2,8,1)"
        )
        connection.commit()
    finally:
        connection.close()

    rig_frames = _core.read_colmap_db(str(path)).rig_frames
    assert rig_frames.frame_data_ids.tolist()[:3] == [2, 2, 100]
    assert rig_frames.frame_sensor_types.tolist()[:3] == [0, 1, 1]


def test_camera_frame_datum_cannot_contradict_existing_image_camera(tmp_path):
    path = tmp_path / "frame-image-camera.db"
    _stock_companion_database(path, "colmap-4.1.1")
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "INSERT INTO rig_sensors"
            "(rig_id,sensor_id,sensor_type,sensor_from_rig) "
            "VALUES(3,7,0,NULL)"
        )
        connection.execute(
            "UPDATE frame_data SET sensor_id=7 "
            "WHERE frame_id=7 AND data_id=2 AND sensor_type=0"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ValueError, match="disagrees with its image camera"):
        _core.read_colmap_db(str(path))


def test_partial_selectors_do_not_decode_unselected_companion_rows(tmp_path):
    path = tmp_path / "partial-companions.db"
    _stock_companion_database(path, "colmap-main-64805cb870b5")
    pair_id = 2 * 2_147_483_647 + 11
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO matches(pair_id,rows,cols,data) VALUES(?,0,2,?)",
            (pair_id, b""),
        )
        connection.execute(
            "UPDATE rig_sensors SET sensor_from_rig=? WHERE rig_id=3",
            (b"",),
        )

    with pytest.raises(ValueError, match="sensor_from_rig byte count"):
        _core.read_colmap_db(str(path))
    assert _core.read_colmap_db_image(str(path), 2).image_id == 2
    assert _core.read_colmap_db_pair(str(path), 11, 2).num_pairs == 1


def test_read_maxx_extension_rows_losslessly(tmp_path):
    path = tmp_path / "maxx-extensions.db"
    expected = _maxx_extension_database(path)

    database = _core.read_colmap_db(str(path))
    features = [database.feature(image_id) for image_id in range(1, 6)]
    graph = database.match_graph
    priors = database.pose_priors
    markers = database.markers
    videos = database.video_metadata
    ownership = database.maxx_schema_info

    assert database.profile == "maxx-v1"
    assert ownership is not None
    assert (
        ownership.schema_version,
        ownership.minimum_reader_version,
        ownership.producer_version,
        ownership.producer_commit,
    ) == (
        1,
        1,
        "3.14.0",
        "de15b08a2dba98b55d6ddfb7cedac147838afbb4",
    )
    assert features[0].time_id == 17
    assert [value.time_id for value in features[1:]] == [None] * 4
    for index, (feature, descriptor) in enumerate(
        zip(features, expected["descriptors"], strict=True)
    ):
        actual = np.asarray(feature.descriptors)
        assert actual.dtype == descriptor.dtype
        assert actual.shape == descriptor.shape
        assert actual.tobytes() == descriptor.tobytes()
        assert feature.descriptor_dtype == descriptor.dtype.name
        assert feature.descriptor_dim == 2
        assert feature.descriptor_dtype_present
        assert feature.descriptor_dim_present
        assert feature.extractor_type == (0, -1, -1, 1, -1)[index]
    assert features[0].extractor_type_name == ""
    assert features[1].extractor_type_name is None
    assert np.asarray(features[0].keypoint_colors).tobytes() == expected[
        "colors"
    ].tobytes()
    assert features[1].keypoint_colors is None
    assert features[0].quality == 0.0
    assert features[1].quality is None

    assert graph.pair_ids.tolist() == [
        expected["pair_id"],
        expected["provenance_only_pair_id"],
    ]
    assert graph.match_present.tolist() == [1, 0]
    assert graph.match_score_present.tolist() == [1, 0]
    assert np.asarray(graph.scores).tobytes() == expected[
        "match_scores"
    ].tobytes()
    assert graph.provenance_present.tolist() == [1, 1]
    assert graph.source_flags.tolist() == [0x80000001, 0]
    assert graph.retrieval_score_present.tolist() == [1, 0]
    assert np.isposinf(graph.retrieval_scores[0])
    assert graph.retrieval_scores[1] == 0.0

    assert priors.rotation_order == "xyzw"
    assert priors.rotation_convention == "cam_from_world"
    assert priors.covariance_storage == "row_major"
    assert (
        priors.rotation_covariance_variable_order == "rotation_tangent_xyz"
    )
    assert (
        priors.pose_covariance_variable_order
        == "rotation_tangent_xyz_translation_xyz"
    )
    assert priors.rotation_covariance_unit == "radians_squared"
    assert priors.position_covariance_unit == "meters_squared"
    assert priors.pose_covariance_cross_unit == "radian_meters"
    assert priors.rotation_present.tolist() == [1]
    assert priors.rotations.tobytes() == expected["rotation"].tobytes()
    assert priors.rotation_covariances.tobytes() == expected[
        "rotation_covariance"
    ].tobytes()
    assert priors.pose_covariances.tobytes() == expected[
        "pose_covariance"
    ].tobytes()

    assert markers.marker_ids.tolist() == [9, 10]
    assert markers.marker_types.tolist() == [2, 0]
    assert markers.world_position_present.tolist() == [1, 0]
    assert markers.world_positions[0].tobytes() == expected[
        "marker_position"
    ].tobytes()
    assert markers.world_position_covariance_present.tolist() == [1, 0]
    assert markers.world_position_covariances[0].tobytes() == expected[
        "marker_covariance"
    ].tobytes()
    assert markers.point3D_ids.tolist() == [2**64 - 1, 123]
    assert markers.projection_point2D_indices.tolist() == [2**32 - 1]
    assert np.isposinf(markers.projection_xy[0, 0])
    assert markers.projection_xy[0, 1] == 20.25
    assert markers.projection_sizes.tolist() == [-3.5]
    assert markers.projection_pinned.tolist() == [1]
    assert markers.projection_coordinate_origin == "top_left"
    assert markers.projection_coordinate_unit == "pixels"
    assert markers.projection_size_unit == "pixels"

    assert videos.video_ids.tolist() == [3, 4]
    assert videos.source_path_present.tolist() == [1, 0]
    assert videos.source_paths == ["", ""]
    assert videos.content_hash_present.tolist() == [0, 1]
    assert videos.content_hashes == ["", ""]
    assert videos.codec_name_present.tolist() == [1, 0]
    assert videos.sync_group_present.tolist() == [1, 0]
    assert videos.video_frame_indices.tolist() == [8]
    assert videos.frame_image_ids.tolist() == [1]
    assert videos.pts_present.tolist() == [1]
    assert np.isposinf(videos.pts_seconds[0])
    assert videos.time_ids.tolist() == [19]


def test_maxx_present_empty_rows_and_deterministic_order(tmp_path):
    path = tmp_path / "maxx-empty-present.db"
    _empty_maxx_de15_database(path)
    pair_id = 1 * 2_147_483_647 + 2
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "INSERT INTO cameras VALUES(7,0,640,480,?,1)",
            (struct.pack("<3d", 500.0, 320.0, 240.0),),
        )
        connection.executemany(
            "INSERT INTO images VALUES(?,?,7,NULL)",
            ((2, "2.jpg"), (1, "1.jpg")),
        )
        connection.execute(
            "INSERT INTO keypoints VALUES(2,0,2,NULL)"
        )
        connection.execute(
            "INSERT INTO descriptors VALUES"
            "(2,0,'SIFT',0,128,0,128,NULL)"
        )
        connection.execute(
            "INSERT INTO keypoint_colors VALUES(2,0,3,NULL)"
        )
        connection.execute(
            "INSERT INTO matches VALUES(?,0,2,NULL)", (pair_id,)
        )
        connection.execute(
            "INSERT INTO match_scores VALUES(?,0,1,NULL)",
            (pair_id,),
        )
        connection.commit()

    database = _core.read_colmap_db(str(path))
    assert database.image_ids == [1, 2]
    empty = database.feature(2)
    assert empty.keypoints_present
    assert empty.keypoints.shape == (0, 2)
    assert empty.descriptors.shape == (0, 128)
    assert empty.keypoint_colors.shape == (0, 3)
    assert database.match_graph.match_present.tolist() == [1]
    assert database.match_graph.match_score_present.tolist() == [1]
    assert database.match_graph.matches.shape == (0, 2)
    assert database.match_graph.scores.shape == (0,)


def test_maxx_extended_pose_null_and_all_nan_blob_presence(tmp_path):
    path = tmp_path / "maxx-pose-ieee.db"
    _maxx_extension_database(path)
    rotation_bits = np.array(
        [
            0x7FF8000000000042,
            0xFFF8000000000011,
            0x7FF0000000000001,
            0xFFF0000000000001,
        ],
        np.uint64,
    )
    logical_pose_bits = np.resize(rotation_bits, 36).reshape(6, 6)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE pose_priors SET rotation=?,"
            "rotation_covariance=NULL,pose_covariance=?",
            (
                rotation_bits.tobytes(),
                logical_pose_bits.T.copy().tobytes(),
            ),
        )

    priors = _core.read_colmap_db(str(path)).pose_priors
    assert priors.rotation_present.tolist() == [1]
    assert priors.rotation_covariance_present.tolist() == [0]
    assert priors.pose_covariance_present.tolist() == [1]
    np.testing.assert_array_equal(
        priors.rotations.view(np.uint64)[0], rotation_bits
    )
    assert priors.rotation_covariances[0].tobytes() == b"\0" * 72
    np.testing.assert_array_equal(
        priors.pose_covariances.view(np.uint64)[0],
        logical_pose_bits,
    )


def test_maxx_successful_scalar_boundaries(tmp_path):
    path = tmp_path / "maxx-scalar-boundaries.db"
    _maxx_extension_database(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE images SET time_id=4294967294 WHERE image_id=1"
        )
        connection.execute(
            "UPDATE markers SET point3D_id=9223372036854775807 "
            "WHERE marker_id=9"
        )
        connection.execute(
            "UPDATE marker_projections SET point2D_idx=4294967294"
        )
        connection.execute(
            "UPDATE videos SET width=-2147483648,height=2147483647,"
            "num_frames=9223372036854775807 WHERE video_id=3"
        )
        connection.execute(
            "UPDATE video_frames SET frame_id=9223372036854775807,"
            "time_id=4294967294"
        )

    database = _core.read_colmap_db(str(path))
    assert database.feature(1).time_id == 2**32 - 2
    assert database.markers.point3D_ids.tolist()[0] == 2**63 - 1
    assert database.markers.projection_point2D_indices.tolist() == [
        2**32 - 2
    ]
    videos = database.video_metadata
    assert videos.widths.tolist()[0] == -(2**31)
    assert videos.heights.tolist()[0] == 2**31 - 1
    assert videos.num_frames.tolist()[0] == 2**63 - 1
    assert videos.video_frame_indices.tolist() == [2**63 - 1]
    assert videos.time_ids.tolist() == [2**32 - 2]


def test_maxx_partial_reads_and_array_lifetimes(tmp_path):
    path = tmp_path / "maxx-partial.db"
    expected = _maxx_extension_database(path)

    image = _core.read_colmap_db_image(str(path), 1)
    pair = _core.read_colmap_db_pair(str(path), 2, 1)
    provenance_only = _core.read_colmap_db_pair(str(path), 101, 100)
    database = _core.read_colmap_db(str(path))
    ownership = database.maxx_schema_info
    arrays = [
        np.asarray(database.feature(image_id).descriptors)
        for image_id in range(1, 6)
    ]
    arrays.extend(
        (
            np.asarray(database.feature(1).keypoint_colors),
            np.asarray(pair.match_score_present),
            np.asarray(pair.scores),
            np.asarray(pair.provenance_present),
            np.asarray(pair.source_flags),
            np.asarray(pair.retrieval_score_present),
            np.asarray(pair.retrieval_scores),
        )
    )
    arrays.extend(
        np.asarray(getattr(database.pose_priors, name))
        for name in (
            "rotation_present",
            "rotations",
            "rotation_covariance_present",
            "rotation_covariances",
            "pose_covariance_present",
            "pose_covariances",
        )
    )
    arrays.extend(
        np.asarray(getattr(database.markers, name))
        for name in (
            "marker_ids",
            "marker_types",
            "world_position_present",
            "world_positions",
            "world_position_covariance_present",
            "world_position_covariances",
            "point3D_ids",
            "enabled",
            "projection_marker_ids",
            "projection_image_ids",
            "projection_xy",
            "projection_sizes",
            "projection_pinned",
            "projection_point2D_indices",
        )
    )
    arrays.extend(
        np.asarray(getattr(database.video_metadata, name))
        for name in (
            "video_ids",
            "source_path_present",
            "content_hash_present",
            "widths",
            "heights",
            "num_frames",
            "fps",
            "duration_seconds",
            "codec_name_present",
            "sync_group_present",
            "frame_video_ids",
            "frame_image_ids",
            "video_frame_indices",
            "pts_present",
            "pts_seconds",
            "time_id_present",
            "time_ids",
        )
    )
    arrays.extend(
        (
            np.asarray(image.descriptors),
            np.asarray(image.keypoint_colors),
        )
    )
    retained = tuple(
        (array, array.dtype.str, array.shape, array.tobytes())
        for array in arrays
    )
    path.unlink()
    del database, image, pair
    gc.collect()

    for array, dtype, shape, payload in retained:
        assert array.dtype.str == dtype
        assert array.shape == shape
        assert array.tobytes() == payload
    assert retained[0][0].tobytes() == expected["descriptors"][0].tobytes()
    assert retained[5][0].tobytes() == expected["colors"].tobytes()
    assert retained[7][0].tobytes() == expected["match_scores"].tobytes()
    assert ownership is not None
    assert (
        ownership.producer_commit
        == "de15b08a2dba98b55d6ddfb7cedac147838afbb4"
    )
    assert provenance_only.num_pairs == 1
    assert provenance_only.match_present.tolist() == [0]
    assert provenance_only.provenance_present.tolist() == [1]
    assert provenance_only.scores is None


def _assert_failed_read_releases(
    path: Path, operation, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        operation()
    released = path.with_suffix(path.suffix + ".released")
    path.rename(released)
    released.unlink()


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        (
            "UPDATE descriptors SET data=x'00' WHERE image_id=1",
            "descriptor data byte count",
        ),
        (
            "UPDATE keypoint_colors SET data=x'00' WHERE image_id=1",
            "keypoint color data byte count",
        ),
        (
            "UPDATE image_qualities SET quality='bad' WHERE image_id=1",
            "image quality must be REAL",
        ),
    ],
)
def test_maxx_partial_image_selected_invalid_and_full_read_release_handle(
    tmp_path, statement, message
):
    path = tmp_path / "selected-image-invalid.db"
    _maxx_extension_database(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(statement)
        connection.commit()

    with pytest.raises(ValueError, match=message):
        _core.read_colmap_db_image(str(path), 1)
    _assert_failed_read_releases(
        path, lambda: _core.read_colmap_db(str(path)), message
    )


@pytest.mark.parametrize(
    ("statement", "parameters", "message"),
    [
        (
            "UPDATE descriptors SET data=x'00' WHERE image_id=5",
            (),
            "descriptor data byte count",
        ),
        (
            "INSERT INTO keypoint_colors VALUES(5,2,3,?)",
            (b"\0",),
            "keypoint color data byte count",
        ),
        (
            "INSERT INTO image_qualities VALUES(5,'bad')",
            (),
            "image quality must be REAL",
        ),
    ],
)
def test_maxx_partial_image_ignores_unselected_invalid_full_read_releases(
    tmp_path, statement, parameters, message
):
    path = tmp_path / "unselected-image-invalid.db"
    _maxx_extension_database(path)
    expected = _feature_fingerprint(
        _core.read_colmap_db_image(str(path), 1)
    )
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(statement, parameters)
        connection.commit()

    selected = _core.read_colmap_db_image(str(path), 1)
    assert _feature_fingerprint(selected) == expected
    _assert_failed_read_releases(
        path, lambda: _core.read_colmap_db(str(path)), message
    )


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        (
            "UPDATE match_scores SET data=x'00'",
            "match score data byte count",
        ),
        (
            "UPDATE pair_provenance SET source_flags='bad' "
            "WHERE retrieval_score IS NOT NULL",
            "pair source_flags must be INTEGER",
        ),
    ],
)
def test_maxx_partial_pair_selected_invalid_and_full_read_release_handle(
    tmp_path, statement, message
):
    path = tmp_path / "selected-pair-invalid.db"
    _maxx_extension_database(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(statement)
        connection.commit()

    with pytest.raises(ValueError, match=message):
        _core.read_colmap_db_pair(str(path), 1, 2)
    _assert_failed_read_releases(
        path, lambda: _core.read_colmap_db(str(path)), message
    )


@pytest.mark.parametrize("surface", ["match_scores", "pair_provenance"])
def test_maxx_partial_pair_ignores_unselected_invalid_full_read_releases(
    tmp_path, surface
):
    path = tmp_path / f"unselected-{surface}.db"
    expected_values = _maxx_extension_database(path)
    expected = _graph_fingerprint(
        _core.read_colmap_db_pair(str(path), 1, 2)
    )
    unrelated_pair = 3 * 2_147_483_647 + 4
    with closing(sqlite3.connect(path)) as connection:
        if surface == "match_scores":
            connection.execute(
                "INSERT INTO matches VALUES(?,1,2,?)",
                (unrelated_pair, struct.pack("<2I", 0, 0)),
            )
            connection.execute(
                "INSERT INTO match_scores VALUES(?,1,1,x'00')",
                (unrelated_pair,),
            )
            message = "match score data byte count"
        else:
            connection.execute(
                "INSERT INTO pair_provenance VALUES(?,'bad',NULL)",
                (unrelated_pair,),
            )
            message = "pair source_flags must be INTEGER"
        connection.commit()

    selected = _core.read_colmap_db_pair(str(path), 2, 1)
    assert _graph_fingerprint(selected) == expected
    assert selected.pair_ids.tolist() == [expected_values["pair_id"]]
    _assert_failed_read_releases(
        path, lambda: _core.read_colmap_db(str(path)), message
    )


def test_maxx_descriptor_metadata_presence_is_independent(tmp_path):
    path = tmp_path / "maxx-descriptor-presence.db"
    _maxx_extension_database(path)
    aliked = np.array(
        [[0.25, -0.5], [1.5, -2.0]], dtype=np.float32
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE descriptors SET type=1,type_name='ALIKED',"
            "dtype=NULL,dim=NULL,cols=8,data=? WHERE image_id=2",
            (aliked.tobytes(),),
        )
        connection.execute(
            "UPDATE descriptors SET dim=NULL WHERE image_id=3"
        )
        connection.execute(
            "UPDATE descriptors SET dtype=NULL,dim=NULL WHERE image_id=5"
        )

    database = _core.read_colmap_db(str(path))
    dtype_absent = database.feature(2)
    dim_absent = database.feature(3)
    both_absent = database.feature(5)

    assert not dtype_absent.descriptor_dtype_present
    assert not dtype_absent.descriptor_dim_present
    assert dtype_absent.descriptors.dtype == np.float32
    assert dtype_absent.descriptors.shape == (2, 2)
    assert dtype_absent.descriptors.tobytes() == aliked.tobytes()
    assert dim_absent.descriptor_dtype_present
    assert not dim_absent.descriptor_dim_present
    assert dim_absent.descriptors.dtype == np.float16
    assert dim_absent.descriptors.shape == (2, 2)
    assert not both_absent.descriptor_dtype_present
    assert not both_absent.descriptor_dim_present
    assert both_absent.descriptors.dtype == np.uint8
    assert both_absent.descriptors.shape == (2, 16)
    inspection = _core.inspect_colmap_db(str(path))
    assert inspection["image_descriptor_dtypes"][1] == "float32"
    assert inspection["image_descriptor_dimensions"][1] == 2


@pytest.mark.parametrize(
    ("surface", "message"),
    [
        ("descriptor", "extended image metadata"),
        ("keypoint_colors", "extended image metadata"),
        ("image_quality", "extended image metadata"),
        ("match_scores", "match scores and provenance"),
        ("pair_provenance", "match scores and provenance"),
        ("extended_pose", "rigs, frames, and pose priors"),
        ("markers", "marker, video metadata, and ownership"),
        ("videos", "marker, video metadata, and ownership"),
        ("ownership", "marker, video metadata, and ownership"),
    ],
)
def test_maxx_writer_guards_each_surface_without_mutating_source_or_destination(
    tmp_path, surface, message
):
    source = tmp_path / f"maxx-{surface}-source.db"
    _maxx_single_surface_database(source, surface)
    database = _core.read_colmap_db(str(source))
    before = _database_fingerprint(database)
    absent = tmp_path / f"{surface}-absent.db"
    existing = tmp_path / f"{surface}-existing.db"
    existing.write_bytes(b"keep-existing")

    for destination in (absent, existing):
        with pytest.raises(ValueError, match=message):
            _core.write_colmap_db(database, str(destination))
        assert _database_fingerprint(database) == before

    assert not absent.exists()
    assert existing.read_bytes() == b"keep-existing"


def test_inspect_maxx_extension_metadata_without_blob_decode(tmp_path):
    path = tmp_path / "maxx-inspect.db"
    _maxx_extension_database(path)

    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE descriptors SET data=x'00'")
        connection.execute("UPDATE keypoint_colors SET data=x'00'")
        connection.execute("UPDATE match_scores SET data=x'00'")
        connection.execute(
            "UPDATE pose_priors SET rotation=x'00',"
            "rotation_covariance='not-a-blob',pose_covariance=x'0001'"
        )
        connection.execute(
            "UPDATE markers SET world_position=x'00',"
            "world_position_cov='not-a-blob'"
        )
    values = _core.inspect_colmap_db(str(path))
    public = sceneio.inspect(path)

    assert values["num_keypoint_color_rows"] == 1
    assert values["num_match_score_pairs"] == 1
    assert values["num_image_qualities"] == 1
    assert values["num_pair_provenance"] == 2
    assert values["num_markers"] == 2
    assert values["num_marker_projections"] == 1
    assert values["num_videos"] == 2
    assert values["num_video_frames"] == 1
    assert values["maxx_schema_info_present"]
    assert values["maxx_schema_version"] == 1
    assert values["maxx_minimum_reader_version"] == 1
    assert values["image_descriptor_dtypes"] == [
        "uint8",
        "int8",
        "float16",
        "float32",
        "float64",
    ]
    assert values["image_descriptor_dimensions"] == [2] * 5
    assert [array.dtype for array in public.arrays if "descriptors" in array.name] == [
        "uint8",
        "int8",
        "float16",
        "float32",
        "float64",
    ]
    assert public.metadata["maxx_schema_version"] == 1
    assert public.metadata["maxx_producer_version"] == "3.14.0"
    assert public.metadata["num_markers"] == 2


def test_inspect_rejects_contradictory_builtin_descriptor_metadata(tmp_path):
    path = tmp_path / "maxx-inspect-contradiction.db"
    _maxx_extension_database(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE descriptors SET type=0,dtype=3 WHERE image_id=2"
        )

    with pytest.raises(ValueError, match="descriptor dtype contradicts"):
        _core.inspect_colmap_db(str(path))


@pytest.mark.parametrize(
    ("statement", "parameters", "message"),
    [
        (
            "UPDATE descriptors SET cols=3 WHERE image_id=2",
            (),
            "descriptor cols disagree",
        ),
        (
            "UPDATE descriptors SET type=0,dtype=3 WHERE image_id=2",
            (),
            "descriptor dtype contradicts",
        ),
        (
            "UPDATE descriptors SET dtype='bad' WHERE image_id=2",
            (),
            "descriptor dtype must be INTEGER",
        ),
        (
            "UPDATE descriptors SET dtype=99 WHERE image_id=2",
            (),
            "descriptor dtype is unknown",
        ),
        (
            "UPDATE descriptors SET data=NULL WHERE image_id=2",
            (),
            "missing descriptor data",
        ),
        (
            "UPDATE descriptors SET type_name=x'00' WHERE image_id=2",
            (),
            "descriptor type_name must be TEXT",
        ),
        (
            "UPDATE descriptors SET dim=-1 WHERE image_id=2",
            (),
            "descriptor dim is outside",
        ),
        (
            "UPDATE keypoint_colors SET cols=2",
            (),
            "keypoint colors must be Nx3",
        ),
        (
            "UPDATE keypoint_colors SET data='bad'",
            (),
            "keypoint color data must be BLOB",
        ),
        (
            "UPDATE keypoint_colors SET image_id=999",
            (),
            "keypoint_colors reference a missing image",
        ),
        (
            "UPDATE match_scores SET rows=1",
            (),
            "match score data byte count",
        ),
        (
            "UPDATE match_scores SET data=NULL",
            (),
            "missing match score data",
        ),
        (
            "UPDATE match_scores SET pair_id=999",
            (),
            "match scores must be parallel",
        ),
        (
            "UPDATE image_qualities SET quality='bad'",
            (),
            "image quality must be REAL",
        ),
        (
            "UPDATE image_qualities SET image_id=999",
            (),
            "image_qualities reference a missing image",
        ),
        (
            "UPDATE pair_provenance SET source_flags=-1 "
            "WHERE retrieval_score IS NOT NULL",
            (),
            "pair source_flags is outside uint32",
        ),
        (
            "UPDATE pair_provenance SET retrieval_score='bad' "
            "WHERE retrieval_score IS NOT NULL",
            (),
            "pair retrieval_score must be REAL",
        ),
        (
            "UPDATE pose_priors SET rotation=?",
            (b"\0" * 8,),
            "rotation byte count",
        ),
        (
            "UPDATE pose_priors SET rotation_covariance=?",
            (b"\0" * 80,),
            "rotation covariance byte count",
        ),
        (
            "UPDATE pose_priors SET pose_covariance='bad'",
            (),
            "pose covariance must be BLOB",
        ),
        (
            "UPDATE markers SET world_position_cov=? WHERE marker_id=9",
            (b"\0" * 8,),
            "marker world_position_cov byte count",
        ),
        (
            "UPDATE markers SET marker_id=4294967295 WHERE marker_id=9",
            (),
            "marker id or type is invalid",
        ),
        (
            "UPDATE markers SET type=4 WHERE marker_id=9",
            (),
            "marker id or type is invalid",
        ),
        (
            "UPDATE markers SET label='' WHERE marker_id=9",
            (),
            "must be non-empty",
        ),
        (
            "UPDATE markers SET enabled=2 WHERE marker_id=9",
            (),
            "marker enabled must be 0 or 1",
        ),
        (
            "UPDATE markers SET point3D_id=-2 WHERE marker_id=9",
            (),
            "point3D_id must be -1 or non-negative",
        ),
        (
            "UPDATE markers SET world_position='bad' WHERE marker_id=9",
            (),
            "marker world_position must be BLOB",
        ),
        (
            "UPDATE marker_projections SET marker_id=999",
            (),
            "marker projection metadata is invalid",
        ),
        (
            "UPDATE marker_projections SET image_id=999",
            (),
            "marker projection references a missing image",
        ),
        (
            "UPDATE marker_projections SET pinned=2",
            (),
            "pinned must be 0 or 1",
        ),
        (
            "UPDATE marker_projections SET point2D_idx=4294967296",
            (),
            "point2D_idx is outside uint32",
        ),
        (
            "UPDATE marker_projections SET x='bad'",
            (),
            "projection x must be REAL",
        ),
        (
            "UPDATE images SET time_id=4294967295 WHERE image_id=1",
            (),
            "time_id must be a valid uint32",
        ),
        (
            "UPDATE images SET time_id=-1 WHERE image_id=1",
            (),
            "time_id must be a valid uint32",
        ),
        (
            "UPDATE video_frames SET time_id=4294967295",
            (),
            "video-frame metadata is invalid",
        ),
        (
            "UPDATE videos SET video_id=4294967295 WHERE video_id=3",
            (),
            "video metadata is invalid",
        ),
        (
            "UPDATE videos SET width=2147483648 WHERE video_id=3",
            (),
            "video width is outside int32",
        ),
        (
            "UPDATE video_frames SET frame_id=-1",
            (),
            "video-frame metadata is invalid",
        ),
        (
            "UPDATE video_frames SET video_id=999",
            (),
            "video-frame metadata is invalid",
        ),
        (
            "UPDATE video_frames SET image_id=999",
            (),
            "video frame references a missing image",
        ),
        (
            "UPDATE video_frames SET pts_seconds='bad'",
            (),
            "pts_seconds must be REAL",
        ),
    ],
)
def test_maxx_extension_malformed_rows_are_rejected(
    tmp_path, statement, parameters, message
):
    path = tmp_path / "maxx-malformed.db"
    _maxx_extension_database(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(statement, parameters)
        connection.commit()

    _assert_failed_read_releases(
        path, lambda: _core.read_colmap_db(str(path)), message
    )


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        (
            "ALTER TABLE descriptors DROP COLUMN dtype",
            "descriptors has an unsupported or incomplete column layout",
        ),
        (
            "DROP TABLE marker_projections",
            "markers and marker_projections must be present together",
        ),
        (
            "DROP TABLE video_frames",
            "videos and video_frames must be present together",
        ),
    ],
)
def test_maxx_extension_incomplete_table_layouts_are_rejected(
    tmp_path, statement, message
):
    path = tmp_path / "maxx-incomplete.db"
    _maxx_extension_database(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(statement)
        connection.commit()

    _assert_failed_read_releases(
        path, lambda: _core.read_colmap_db(str(path)), message
    )


def test_stock_companion_writer_guard_does_not_touch_destination(tmp_path):
    source = tmp_path / "stock-companions.db"
    _stock_companion_database(source, "colmap-4.1.1")
    database = _core.read_colmap_db(str(source))
    absent = tmp_path / "absent.db"
    existing = tmp_path / "existing.db"
    existing.write_bytes(b"preserve-this-destination")
    before = existing.read_bytes()

    for destination in (absent, existing):
        with pytest.raises(
            ValueError, match="rigs, frames, and pose priors"
        ):
            _core.write_colmap_db(database, str(destination))

    assert not absent.exists()
    assert existing.read_bytes() == before


def test_read_current_profile_recovered_cameras_and_partial_pair(tmp_path):
    path = tmp_path / "current.db"
    camera1_blob = _recovered_camera_blob()
    camera2_blob = _recovered_camera_blob(
        camera_id=24,
        model_id=0,
        width=800,
        height=600,
        prior_focal_length=0,
        params=(700.0, 400.0, 300.0),
    )
    _current_recovered_camera_database(
        path, camera1=camera1_blob, camera2=camera2_blob
    )

    database = _core.read_colmap_db(str(path))
    partial = _core.read_colmap_db_pair(str(path), 11, 2)

    assert database.profile == "colmap-main-64805cb870b5"
    assert database.match_graph.camera1_present.tolist() == [1]
    assert database.match_graph.camera2_present.tolist() == [1]
    assert database.match_graph.camera1_prior_focal_length.tolist() == [1]
    assert database.match_graph.camera2_prior_focal_length.tolist() == [0]
    assert _camera_fingerprint(database.match_graph.recovered_camera1(0)) == (
        23,
        1,
        640,
        480,
        np.array([500.0, 501.0, 320.0, 240.0], np.float64).tobytes(),
    )
    assert _camera_fingerprint(database.match_graph.recovered_camera2(0)) == (
        24,
        0,
        800,
        600,
        np.array([700.0, 400.0, 300.0], np.float64).tobytes(),
    )
    assert _graph_fingerprint(partial) == _graph_fingerprint(database.match_graph)


def test_read_current_profile_preserves_null_recovered_camera(tmp_path):
    path = tmp_path / "current-null.db"
    _current_recovered_camera_database(path, camera1=None, camera2=None)

    graph = _core.read_colmap_db(str(path)).match_graph

    assert graph.camera1_present.tolist() == [0]
    assert graph.camera2_present.tolist() == [0]
    assert graph.camera1_prior_focal_length.tolist() == [0]
    assert graph.camera2_prior_focal_length.tolist() == [0]
    assert graph.recovered_camera1(0) is None
    assert graph.recovered_camera2(0) is None
    with pytest.raises(IndexError):
        graph.recovered_camera1(1)


def test_read_current_profile_preserves_asymmetric_endpoint_nulls_and_pair_filter(
    tmp_path,
):
    path = tmp_path / "current-asymmetric.db"
    selected_blob = _recovered_camera_blob(
        camera_id=44,
        model_id=0,
        width=800,
        height=600,
        prior_focal_length=0,
        params=(700.0, 400.0, 300.0),
    )
    _current_recovered_camera_pairs_database(
        path,
        [
            (2, 11, _recovered_camera_blob(camera_id=23), None),
            (3, 11, None, selected_blob),
        ],
    )

    full = _core.read_colmap_db(str(path)).match_graph
    selected = _core.read_colmap_db_pair(str(path), 11, 3)
    expected_camera = _core.camera(
        44,
        0,
        800,
        600,
        np.array([700.0, 400.0, 300.0], np.float64),
    )
    expected = _core.match_graph(
        np.array([[3, 11]], np.uint32),
        np.array([0, 0], np.uint64),
        np.empty((0, 2), np.uint32),
        np.array([0, 0], np.uint64),
        np.empty((0, 2), np.uint32),
        recovered_camera1=[None],
        recovered_camera2=[expected_camera],
        camera2_prior_focal_length=np.array([0], np.uint8),
        match_present=np.array([0], np.uint8),
    )

    assert full.camera1_present.tolist() == [1, 0]
    assert full.camera2_present.tolist() == [0, 1]
    assert full.camera1_prior_focal_length.tolist() == [1, 0]
    assert full.camera2_prior_focal_length.tolist() == [0, 0]
    assert _graph_fingerprint(selected) == _graph_fingerprint(expected)


def test_partial_pair_does_not_decode_malformed_unselected_camera(tmp_path):
    path = tmp_path / "current-filtered.db"
    selected_blob = _recovered_camera_blob(camera_id=44)
    _current_recovered_camera_pairs_database(
        path,
        [
            (2, 11, b"\0" * 32, None),
            (3, 11, None, selected_blob),
        ],
    )

    with pytest.raises(ValueError, match="truncated camera1 blob"):
        _core.read_colmap_db(str(path))
    selected = _core.read_colmap_db_pair(str(path), 11, 3)
    assert selected.image_pairs.tolist() == [[3, 11]]
    assert selected.camera1_present.tolist() == [0]
    assert selected.camera2_present.tolist() == [1]
    assert selected.recovered_camera2(0).id == 44


def test_recovered_camera_uses_full_upstream_integer_domain(tmp_path):
    path = tmp_path / "current-boundary.db"
    _current_recovered_camera_database(
        path,
        camera1=_recovered_camera_blob(
            camera_id=2**32 - 2,
            width=2**63 + 17,
            height=2**64 - 1,
        ),
    )

    recovered = _core.read_colmap_db(str(path)).match_graph.recovered_camera1(0)

    assert recovered.id == 2**32 - 2
    assert recovered.width == 2**63 + 17
    assert recovered.height == 2**64 - 1
    constructed = _core.camera(
        2**32 - 2,
        1,
        2**63 + 17,
        2**64 - 1,
        np.array([500.0, 501.0, 320.0, 240.0], np.float64),
    )
    assert _camera_fingerprint(constructed) == _camera_fingerprint(recovered)
    with pytest.raises(ValueError, match="UINT32_MAX"):
        _core.camera(
            2**32 - 1,
            1,
            640,
            480,
            np.array([500.0, 501.0, 320.0, 240.0], np.float64),
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        pytest.param(
            b"\0" * 32, "truncated camera1 blob", id="short-header"
        ),
        pytest.param(
            _recovered_camera_blob() + b"\0",
            "trailing bytes",
            id="trailing-byte",
        ),
        pytest.param(
            _recovered_camera_blob(prior_focal_length=2),
            "prior_focal_length must be 0 or 1",
            id="invalid-prior-flag",
        ),
        pytest.param(
            _recovered_camera_blob(params=(1.0, 2.0, 3.0)),
            "parameter count disagrees",
            id="wrong-parameter-count",
        ),
        pytest.param(
            _recovered_camera_blob(model_id=99, params=()),
            "unknown camera model",
            id="unknown-model",
        ),
        pytest.param(
            _recovered_camera_blob(width=0),
            "dimensions must be positive",
            id="zero-width",
        ),
        pytest.param(
            _recovered_camera_blob(params=(np.nan, 1.0, 2.0, 3.0)),
            "parameters must be finite",
            id="nonfinite-parameter",
        ),
        pytest.param(
            _recovered_camera_blob()[:-1],
            "truncated camera1 parameter payload",
            id="short-parameters",
        ),
        pytest.param(
            struct.pack(
                "<IiQQBQ",
                23,
                1,
                640,
                480,
                1,
                2**64 - 1,
            ),
            "parameter count overflows size_t",
            id="overflowing-parameter-count",
        ),
        pytest.param(
            _recovered_camera_blob(camera_id=2**32 - 1),
            "UINT32_MAX",
            id="invalid-camera-id",
        ),
        pytest.param(
            "not-a-blob",
            "must be BLOB or NULL",
            id="wrong-sql-type",
        ),
    ],
)
def test_read_current_profile_rejects_malformed_recovered_camera(
    tmp_path, payload, message
):
    path = tmp_path / "malformed-current.db"
    _current_recovered_camera_database(path, camera1=payload)

    with pytest.raises(ValueError, match=message):
        _core.read_colmap_db(str(path))
    with pytest.raises(ValueError, match=message):
        _core.read_colmap_db_pair(str(path), 11, 2)
    renamed = path.with_suffix(".released")
    path.rename(renamed)


def test_exact_profile_writer_is_guarded_until_profile_writers_land(tmp_path):
    path = tmp_path / "stock.db"
    _empty_profile_database(path, "colmap-4.1.1")
    database = _core.read_colmap_db(str(path))

    with pytest.raises(ValueError, match="exact profile preservation"):
        _core.write_colmap_db(database, str(tmp_path / "converted.db"))


@pytest.mark.parametrize(
    "profile",
    [
        "colmap-3.13.0",
        "colmap-4.1.1",
        "colmap-main-64805cb870b5",
    ],
)
def test_exact_stock_profile_writer_preserves_populated_companions(
    tmp_path, profile
):
    source = tmp_path / f"{profile}-source.db"
    destination = tmp_path / f"{profile}-roundtrip.db"
    _stock_companion_database(source, profile)
    expected = _core.read_colmap_db(str(source))

    _core.write_colmap_db(expected, str(destination), profile=profile)
    actual = _core.read_colmap_db(str(destination))

    assert _database_fingerprint(actual) == _database_fingerprint(expected)
    assert _sqlite_rows(destination) == _sqlite_rows(source)
    assert _core.inspect_colmap_db(str(destination))["profile"] == profile


def test_exact_current_profile_writer_preserves_recovered_cameras(tmp_path):
    source = tmp_path / "current-source.db"
    destination = tmp_path / "current-roundtrip.db"
    _current_recovered_camera_database(
        source,
        camera1=_recovered_camera_blob(),
        camera2=_recovered_camera_blob(
            camera_id=24,
            model_id=0,
            width=800,
            height=600,
            prior_focal_length=0,
            params=(700.0, 400.0, 300.0),
        ),
    )
    expected = _core.read_colmap_db(str(source))

    _core.write_colmap_db(
        expected,
        str(destination),
        profile="colmap-main-64805cb870b5",
    )
    actual = _core.read_colmap_db(str(destination))

    assert _database_fingerprint(actual) == _database_fingerprint(expected)
    assert _sqlite_rows(destination) == _sqlite_rows(source)


def test_exact_maxx_profile_writer_preserves_every_owned_surface(tmp_path):
    source = tmp_path / "maxx-source.db"
    destination = tmp_path / "maxx-roundtrip.db"
    _maxx_extension_database(source)
    expected = _core.read_colmap_db(str(source))

    _core.write_colmap_db(expected, str(destination), profile="maxx-v1")
    actual = _core.read_colmap_db(str(destination))

    assert _database_fingerprint(actual) == _database_fingerprint(expected)
    assert _sqlite_rows(destination) == _sqlite_rows(source)
    assert _core.inspect_colmap_db(str(destination))["profile"] == "maxx-v1"


def test_public_exact_profile_writer_and_conversion_report(tmp_path):
    source = tmp_path / "stock-source.db"
    destination = tmp_path / "stock-public.db"
    inferred_destination = tmp_path / "stock-public-preserved.db"
    _stock_companion_database(source, "colmap-4.1.1")
    database = sceneio.read(source, format="colmap_db")

    report = sceneio.colmap_database_conversion_report(
        database, profile="colmap-4.1.1"
    )
    assert report == db_contract.ColmapDatabaseConversionReport(
        source_profile="colmap-4.1.1",
        target_profile="colmap-4.1.1",
        writable=True,
        identity_changes=(),
        incompatibilities=(),
    )

    sceneio.write(
        database,
        destination,
        format="colmap_db",
        profile="colmap-4.1.1",
    )
    assert _database_fingerprint(sceneio.read(destination)) == (
        _database_fingerprint(database)
    )
    sceneio.write(database, inferred_destination, format="colmap_db")
    assert _database_fingerprint(sceneio.read(inferred_destination)) == (
        _database_fingerprint(database)
    )


def test_conversion_report_lists_all_incompatible_maxx_categories(tmp_path):
    source = tmp_path / "maxx-rich.db"
    _maxx_extension_database(source)
    database = _core.read_colmap_db(str(source))

    report = sceneio.colmap_database_conversion_report(
        database, profile="colmap-4.1.1"
    )

    assert not report.writable
    assert report.identity_changes == (
        ("profile", "maxx-v1", "colmap-4.1.1"),
        ("application_id", 0x4D415858, 0),
        ("user_version", 3_140_003, 4_010_100),
    )
    assert report.incompatibilities == (
        "selected stock profile cannot represent MAXX image or "
        "descriptor metadata",
        "selected stock profile cannot preserve a descriptor dtype "
        "that differs from its extractor-type inference",
        "selected stock profile cannot represent extended pose-prior fields",
        "selected stock profile cannot represent match scores or provenance",
        "selected stock profile cannot represent MAXX companion records",
    )
    destination = tmp_path / "refused-stock.db"
    source_before = _database_fingerprint(database)
    with pytest.raises(
        sceneio.FormatError, match="cannot represent MAXX"
    ):
        sceneio.write(
            database,
            destination,
            format="colmap_db",
            profile="colmap-4.1.1",
        )
    assert not destination.exists()
    assert _database_fingerprint(database) == source_before


def test_conversion_report_maxx_ownership_and_refusal_matrix(tmp_path):
    missing_ownership = sceneio.colmap_database_conversion_report(
        _database(), profile="maxx-v1"
    )
    assert (
        "maxx-v1 requires an explicit ownership row"
        in missing_ownership.incompatibilities
    )
    assert all(
        "ownership versions" not in issue
        for issue in missing_ownership.incompatibilities
    )

    invalid_ownership = _core.colmap_maxx_schema_info(
        2, 1, "producer", "commit"
    )
    invalid_maxx = _core.colmap_database(
        _database().cameras,
        [_database().feature_at(0), _database().feature_at(1)],
        _database().match_graph,
        prior_focal_length=np.array([1], np.uint8),
        maxx_schema_info=invalid_ownership,
    )
    assert (
        "maxx-v1 ownership versions must both equal 1"
        in sceneio.colmap_database_conversion_report(
            invalid_maxx, profile="maxx-v1"
        ).incompatibilities
    )

    scored = _core.feature_set(
        np.zeros((3, 2), np.float32),
        np.zeros((3, 8), np.uint8),
        scores=np.full(3, 0.5, np.float32),
        image_id=2,
        image_name="a.jpg",
        camera_id=5,
        image_size=(640, 480),
        extractor_type=0,
    )
    score_report = sceneio.colmap_database_conversion_report(
        _database(features=[scored, _feature(11, "b.jpg")]),
        profile="colmap-4.1.1",
    )
    assert any(
        "per-keypoint scores" in issue
        for issue in score_report.incompatibilities
    )

    non_sift = _core.feature_set(
        np.zeros((3, 2), np.float32),
        np.zeros((3, 8), np.float32),
        image_id=2,
        image_name="a.jpg",
        camera_id=5,
        image_size=(640, 480),
        extractor_type=1,
    )
    descriptor_report = sceneio.colmap_database_conversion_report(
        _database(features=[non_sift, _feature(11, "b.jpg")]),
        profile="colmap-3.13.0",
    )
    assert "COLMAP 3.13 descriptors must be uint8 SIFT" in (
        descriptor_report.incompatibilities
    )

    generalized_path = tmp_path / "generalized.db"
    _stock_companion_database(generalized_path, "colmap-4.1.1")
    prior_report = sceneio.colmap_database_conversion_report(
        sceneio.read(generalized_path), profile="colmap-3.13.0"
    )
    assert (
        "pose-prior layout does not match the selected profile"
        in prior_report.incompatibilities
    )
    too_large_prior = sceneio.read(generalized_path)
    too_large_prior.pose_priors.correlated_data_ids[0] = (
        np.iinfo(np.uint64).max
    )
    assert "pose-prior data_id exceeds SQLite INTEGER" in (
        sceneio.colmap_database_conversion_report(
            too_large_prior, profile="colmap-4.1.1"
        ).incompatibilities
    )

    recovered_path = tmp_path / "recovered.db"
    _current_recovered_camera_database(
        recovered_path,
        camera1=_recovered_camera_blob(),
        camera2=None,
    )
    recovered_report = sceneio.colmap_database_conversion_report(
        sceneio.read(recovered_path), profile="colmap-4.1.1"
    )
    assert any(
        "recovered two-view cameras" in issue
        for issue in recovered_report.incompatibilities
    )

    too_large_path = tmp_path / "too-large.db"
    _stock_companion_database(too_large_path, "colmap-4.1.1")
    too_large = sceneio.read(too_large_path)
    too_large.rig_frames.frame_data_ids[0] = np.iinfo(np.uint64).max
    bound_report = sceneio.colmap_database_conversion_report(
        too_large, profile="colmap-4.1.1"
    )
    assert "frame data_id exceeds SQLite INTEGER" in (
        bound_report.incompatibilities
    )

    marker_path = tmp_path / "too-large-marker.db"
    _maxx_extension_database(marker_path)
    too_large_marker = sceneio.read(marker_path)
    too_large_marker.markers.point3D_ids[0] = np.iinfo(np.uint64).max - 1
    assert "marker point3D_id exceeds SQLite INTEGER" in (
        sceneio.colmap_database_conversion_report(
            too_large_marker, profile="maxx-v1"
        ).incompatibilities
    )


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("retrieval", "present retrieval score cannot be NaN"),
        ("pts", "video-frame metadata is invalid"),
        ("projection", "marker projection REAL values cannot be NaN"),
        ("fps", "video REAL values cannot be NaN"),
        ("duration", "video REAL values cannot be NaN"),
    ],
)
def test_exact_writer_rejects_nan_real_without_opening_destination(
    tmp_path, field, message
):
    source = tmp_path / f"nan-{field}-source.db"
    destination = tmp_path / f"nan-{field}-destination.db"
    _maxx_extension_database(source)
    database = sceneio.read(source)
    if field == "retrieval":
        database.match_graph.retrieval_scores[0] = np.nan
    elif field == "pts":
        database.video_metadata.pts_seconds[0] = np.nan
    elif field == "projection":
        database.markers.projection_xy[0, 0] = np.nan
    elif field == "fps":
        database.video_metadata.fps[0] = np.nan
    else:
        database.video_metadata.duration_seconds[0] = np.nan

    with pytest.raises(ValueError, match=message):
        sceneio.colmap_database_conversion_report(
            database, profile="maxx-v1"
        )
    with pytest.raises(sceneio.FormatError, match=message):
        sceneio.write_colmap_db(
            database, destination, profile="maxx-v1"
        )
    assert not destination.exists()


def test_unknown_profile_report_and_write_do_not_create_destination(tmp_path):
    destination = tmp_path / "unknown-profile.db"
    database = _database()

    with pytest.raises(ValueError, match="unknown target profile"):
        sceneio.colmap_database_conversion_report(
            database, profile="not-a-profile"
        )
    with pytest.raises(sceneio.FormatError, match="unknown target profile"):
        sceneio.write_colmap_db(
            database,
            destination,
            profile="not-a-profile",
        )

    assert not destination.exists()

    with pytest.raises(ValueError, match="unknown target profile"):
        sceneio.colmap_database_conversion_report(
            database, profile="sceneio-hybrid-v1"
        )
    with pytest.raises(sceneio.FormatError, match="unknown target profile"):
        sceneio.write_colmap_db(
            database,
            destination,
            profile="sceneio-hybrid-v1",
        )
    assert not destination.exists()


def test_public_write_rejects_profile_for_other_formats_before_output(tmp_path):
    destination = tmp_path / "wrong.npy"

    with pytest.raises(
        sceneio.FormatError, match="only when writing format 'colmap_db'"
    ):
        sceneio.write(
            np.arange(3, dtype=np.float32),
            destination,
            format="npy",
            profile="colmap-4.1.1",
        )

    assert not destination.exists()


def test_legacy_writer_rejects_recovered_two_view_cameras(tmp_path):
    camera = _core.camera(
        23,
        1,
        640,
        480,
        np.array([500.0, 501.0, 320.0, 240.0], np.float64),
    )
    graph = _core.match_graph(
        np.array([[2, 11]], np.uint32),
        np.array([0, 0], np.uint64),
        np.empty((0, 2), np.uint32),
        np.array([0, 0], np.uint64),
        np.empty((0, 2), np.uint32),
        recovered_camera1=[camera],
    )
    value = _database(graph=graph)

    with pytest.raises(ValueError, match="recovered two-view cameras"):
        _core.write_colmap_db(value, str(tmp_path / "legacy.db"))


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


def _sqlite_rows(path: Path) -> dict[str, tuple[tuple[object, ...], ...]]:
    """Return table rows through stdlib SQLite, independent of the codec."""

    with sqlite3.connect(path) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' ORDER BY name"
            )
        ]
        return {
            table: tuple(
                sorted(
                    connection.execute(
                        f'SELECT * FROM "{table}"'
                    ).fetchall(),
                    key=repr,
                )
            )
            for table in tables
        }


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
        value.extractor_type_name,
        value.descriptor_dtype_present,
        value.descriptor_dim_present,
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
        (
            None
            if value.keypoint_colors is None
            else np.asarray(value.keypoint_colors).tobytes()
        ),
        None if value.scores is None else np.asarray(value.scores).tobytes(),
        value.quality,
    )


def _graph_fingerprint(value):
    names = (
        "pair_ids",
        "image_pairs",
        "match_present",
        "match_score_present",
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
        "camera1_present",
        "camera2_present",
        "camera1_prior_focal_length",
        "camera2_prior_focal_length",
        "provenance_present",
        "source_flags",
        "retrieval_score_present",
        "retrieval_scores",
    )
    arrays = tuple(
        (np.asarray(getattr(value, name)).dtype.str, np.asarray(getattr(value, name)).shape,
         np.asarray(getattr(value, name)).tobytes())
        for name in names
    )
    cameras = tuple(
        (
            _camera_fingerprint(value.recovered_camera1(index)),
            _camera_fingerprint(value.recovered_camera2(index)),
        )
        for index in range(value.num_pairs)
    )
    scores = (
        None
        if value.scores is None
        else (
            np.asarray(value.scores).dtype.str,
            np.asarray(value.scores).shape,
            np.asarray(value.scores).tobytes(),
        )
    )
    return arrays, scores, cameras


def _camera_fingerprint(value):
    if value is None:
        return None
    return (
        value.id,
        value.model_id,
        value.width,
        value.height,
        np.asarray(value.params).tobytes(),
    )


def _array_fields_fingerprint(value, names):
    return tuple(
        (
            np.asarray(getattr(value, name)).dtype.str,
            np.asarray(getattr(value, name)).shape,
            np.asarray(getattr(value, name)).tobytes(),
        )
        for name in names
    )


def _database_fingerprint(value):
    ownership = value.maxx_schema_info
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
        _array_fields_fingerprint(
            value.rig_frames,
            (
                "rig_ids",
                "rig_reference_sensor_types",
                "rig_reference_sensor_ids",
                "rig_sensor_offsets",
                "rig_sensor_types",
                "rig_sensor_ids",
                "rig_sensor_pose_present",
                "rig_sensor_quaternions",
                "rig_sensor_translations",
                "frame_ids",
                "frame_rig_ids",
                "frame_data_offsets",
                "frame_data_ids",
                "frame_sensor_types",
                "frame_sensor_ids",
            ),
        ),
        (
            value.pose_priors.generalized,
            _array_fields_fingerprint(
                value.pose_priors,
                (
                    "prior_ids",
                    "correlated_data_ids",
                    "correlated_sensor_ids",
                    "correlated_sensor_types",
                    "coordinate_systems",
                    "position_present",
                    "positions",
                    "position_covariance_present",
                    "position_covariances",
                    "gravity_present",
                    "gravities",
                    "rotation_present",
                    "rotations",
                    "rotation_covariance_present",
                    "rotation_covariances",
                    "pose_covariance_present",
                    "pose_covariances",
                ),
            ),
        ),
        (
            tuple(value.markers.labels),
            _array_fields_fingerprint(
                value.markers,
                (
                    "marker_ids",
                    "marker_types",
                    "world_position_present",
                    "world_positions",
                    "world_position_covariance_present",
                    "world_position_covariances",
                    "point3D_ids",
                    "enabled",
                    "projection_marker_ids",
                    "projection_image_ids",
                    "projection_xy",
                    "projection_sizes",
                    "projection_pinned",
                    "projection_point2D_indices",
                ),
            ),
        ),
        (
            tuple(value.video_metadata.names),
            tuple(value.video_metadata.source_paths),
            tuple(value.video_metadata.content_hashes),
            tuple(value.video_metadata.codec_names),
            tuple(value.video_metadata.sync_groups),
            _array_fields_fingerprint(
                value.video_metadata,
                (
                    "video_ids",
                    "source_path_present",
                    "content_hash_present",
                    "widths",
                    "heights",
                    "num_frames",
                    "fps",
                    "duration_seconds",
                    "codec_name_present",
                    "sync_group_present",
                    "frame_video_ids",
                    "frame_image_ids",
                    "video_frame_indices",
                    "pts_present",
                    "pts_seconds",
                    "time_id_present",
                    "time_ids",
                ),
            ),
        ),
        (
            None
            if ownership is None
            else (
                ownership.schema_version,
                ownership.minimum_reader_version,
                ownership.producer_version,
                ownership.producer_commit,
            )
        ),
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
        extractor_type=0,
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


def test_match_graph_recovered_camera_contract_and_lifetime():
    camera1 = _core.camera(
        23,
        1,
        640,
        480,
        np.array([500.0, 501.0, 320.0, 240.0], np.float64),
    )
    camera2 = _core.camera(
        24,
        0,
        800,
        600,
        np.array([700.0, 400.0, 300.0], np.float64),
    )
    value = _core.match_graph(
        np.array([[2, 11]], np.uint32),
        np.array([0, 0], np.uint64),
        np.empty((0, 2), np.uint32),
        np.array([0, 0], np.uint64),
        np.empty((0, 2), np.uint32),
        recovered_camera1=[camera1],
        camera1_prior_focal_length=np.array([1], np.uint8),
        recovered_camera2=[camera2],
        camera2_prior_focal_length=np.array([0], np.uint8),
    )

    assert value.camera1_present.tolist() == [1]
    assert value.camera2_present.tolist() == [1]
    assert value.camera1_prior_focal_length.tolist() == [1]
    assert value.camera2_prior_focal_length.tolist() == [0]
    recovered = value.recovered_camera1(0)
    assert _camera_fingerprint(recovered) == _camera_fingerprint(camera1)
    params = recovered.params
    expected = params.copy()
    del value, recovered
    gc.collect()
    np.testing.assert_array_equal(params, expected)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        pytest.param(
            {
                "camera1_prior_focal_length": np.array([1], np.uint8),
            },
            "absent recovered_camera1",
            id="prior-without-camera",
        ),
        pytest.param(
            {
                "recovered_camera1": [
                    _core.camera(
                        23,
                        0,
                        10,
                        10,
                        np.array([5.0, 5.0, 5.0], np.float64),
                    )
                ],
                "camera1_present": np.array([0], np.uint8),
            },
            "camera1_present must agree",
            id="camera-marked-absent",
        ),
        pytest.param(
            {
                "recovered_camera1": [],
            },
            "must have P camera-or-None values",
            id="wrong-camera-count",
        ),
        pytest.param(
            {
                "recovered_camera1": [
                    _core.camera(
                        23,
                        0,
                        10,
                        10,
                        np.array([5.0, 5.0, 5.0], np.float64),
                    )
                ],
                "geometry_present": np.array([0], np.uint8),
            },
            "absent geometry",
            id="camera-without-geometry-row",
        ),
    ],
)
def test_match_graph_recovered_camera_rejects_inconsistent_presence(
    kwargs, message
):
    with pytest.raises(ValueError, match=message):
        _core.match_graph(
            np.array([[2, 11]], np.uint32),
            np.array([0, 0], np.uint64),
            np.empty((0, 2), np.uint32),
            np.array([0, 0], np.uint64),
            np.empty((0, 2), np.uint32),
            **kwargs,
        )


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


def test_pycolmap_reads_sceneio_exact_411_writer(tmp_path):
    pycolmap = pytest.importorskip("pycolmap")
    source = tmp_path / "exact-411-source.db"
    destination = tmp_path / "exact-411-sceneio.db"
    _stock_companion_database(source, "colmap-4.1.1")
    sceneio.write_colmap_db(
        sceneio.read(source),
        destination,
        profile="colmap-4.1.1",
    )

    database = pycolmap.Database.open(destination)
    try:
        assert database.num_cameras() == 2
        assert database.num_images() == 2
        images = {
            image.image_id: image
            for image in database.read_all_images()
        }
        assert images[2].name == "2.jpg"
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
    capabilities = sceneio.capabilities("colmap_db")
    assert capabilities.partial_selectors == ("image_id", "pair")
    assert "stock_rig_frame_reads" in capabilities.supported_features
    assert "stock_pose_prior_reads" in capabilities.supported_features
    assert "stock_rig_frame_writes" in capabilities.supported_features
    assert "stock_pose_prior_writes" in capabilities.supported_features
    assert capabilities.unsupported_features == ("per_keypoint_score_writes",)


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
    for stage in (1, 2, 3):
        with pytest.raises(RuntimeError, match="injected failure"):
            _core.write_colmap_db(expected, str(path), _test_fail_after=stage)
        assert _database_fingerprint(_core.read_colmap_db(str(path))) == before


def test_exact_profile_writer_rolls_back_every_stage_and_cleans_new_files(tmp_path):
    source = tmp_path / "maxx-source.db"
    existing = tmp_path / "maxx-existing.db"
    _maxx_extension_database(source)
    _maxx_extension_database(existing)
    expected = _core.read_colmap_db(str(source))
    before = _database_fingerprint(_core.read_colmap_db(str(existing)))

    for stage in (1, 2, 3):
        with pytest.raises(RuntimeError, match="injected failure"):
            _core.write_colmap_db(
                expected,
                str(existing),
                profile="maxx-v1",
                _test_fail_after=stage,
            )
        assert _database_fingerprint(_core.read_colmap_db(str(existing))) == before
        assert not list(tmp_path.glob(f"{existing.name}-*"))

        absent = tmp_path / f"maxx-new-stage-{stage}.db"
        with pytest.raises(RuntimeError, match="injected failure"):
            _core.write_colmap_db(
                expected,
                str(absent),
                profile="maxx-v1",
                _test_fail_after=stage,
            )
        assert not absent.exists()
        assert not list(tmp_path.glob(f"{absent.name}-*"))


@pytest.mark.parametrize(
    ("object_type", "ddl"),
    [
        ("view", "CREATE VIEW extra_object AS SELECT * FROM cameras"),
        (
            "trigger",
            "CREATE TRIGGER extra_object AFTER INSERT ON cameras "
            "BEGIN SELECT 1; END",
        ),
        ("index", "CREATE INDEX extra_object ON cameras(model)"),
    ],
)
def test_exact_writer_refuses_unrepresented_schema_objects(
    tmp_path, object_type, ddl
):
    source = tmp_path / "stock-source.db"
    destination = tmp_path / f"with-extra-{object_type}.db"
    _stock_companion_database(source, "colmap-4.1.1")
    _stock_companion_database(destination, "colmap-4.1.1")
    database = _core.read_colmap_db(str(source))
    with sqlite3.connect(destination) as connection:
        connection.execute(ddl)
        connection.commit()

    with pytest.raises(ValueError, match="unsupported schema object"):
        _core.write_colmap_db(
            database,
            str(destination),
            profile="colmap-4.1.1",
        )

    with sqlite3.connect(destination) as connection:
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master "
            "WHERE type=? AND name='extra_object'",
            (object_type,),
        ).fetchone() == (1,)


def test_exact_writer_refuses_misleading_known_index_without_mutation(
    tmp_path,
):
    source = tmp_path / "stock-source.db"
    destination = tmp_path / "misleading-index.db"
    _stock_companion_database(source, "colmap-4.1.1")
    _stock_companion_database(destination, "colmap-4.1.1")
    database = _core.read_colmap_db(str(source))
    with sqlite3.connect(destination) as connection:
        connection.execute("DROP INDEX rig_ref_sensor_assignment")
        connection.execute(
            "CREATE INDEX rig_ref_sensor_assignment ON cameras(model)"
        )
        connection.commit()
    before = destination.read_bytes()

    with pytest.raises(ValueError, match="unsupported schema object"):
        _core.write_colmap_db(
            database,
            str(destination),
            profile="colmap-4.1.1",
        )

    assert destination.read_bytes() == before
    assert not list(tmp_path.glob(f"{destination.name}-*"))


def test_exact_writer_refuses_unknown_table_without_mutation(tmp_path):
    source = tmp_path / "stock-source.db"
    destination = tmp_path / "unknown-table.db"
    _stock_companion_database(source, "colmap-4.1.1")
    _stock_companion_database(destination, "colmap-4.1.1")
    database = _core.read_colmap_db(str(source))
    with sqlite3.connect(destination) as connection:
        connection.execute("CREATE TABLE ecosystem_extra(value BLOB)")
        connection.execute("INSERT INTO ecosystem_extra VALUES(x'0102')")
        connection.commit()
    before = destination.read_bytes()

    with pytest.raises(ValueError, match="unsupported table"):
        _core.write_colmap_db(
            database,
            str(destination),
            profile="colmap-4.1.1",
        )

    assert destination.read_bytes() == before
    assert not list(tmp_path.glob(f"{destination.name}-*"))


def test_hybrid_writer_replaces_preexisting_maxx_identity_and_tables(
    tmp_path,
):
    path = tmp_path / "replace-maxx.db"
    _maxx_extension_database(path)
    expected = _database()
    source_before = _database_fingerprint(expected)

    sceneio.write(expected, path)

    assert _database_fingerprint(expected) == source_before
    with sqlite3.connect(path) as connection:
        application_id = connection.execute(
            "PRAGMA application_id"
        ).fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert application_id == 0
    assert {
        "keypoint_colors",
        "match_scores",
        "pair_provenance",
        "maxx_schema_info",
    }.isdisjoint(tables)
    assert {
        "image_qualities",
        "markers",
        "marker_projections",
        "videos",
        "video_frames",
    } <= tables
    with sqlite3.connect(path) as connection:
        assert all(
            connection.execute(
                f'SELECT count(*) FROM "{table}"'
            ).fetchone()[0]
            == 0
            for table in (
                "image_qualities",
                "markers",
                "marker_projections",
                "videos",
                "video_frames",
            )
        )
    assert _database_fingerprint(
        _core.read_colmap_db(str(path))
    ) == source_before


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
        extractor_type=-1,
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


def test_nonempty_rig_table_is_represented_and_handle_released(tmp_path):
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
    database = sceneio.read(path)
    assert database.rig_frames.rig_ids.tolist() == [1]
    assert database.rig_frames.num_frames == 0
    del database
    gc.collect()
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
                    extractor_type=int(rng.choice([-1, 0])),
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
