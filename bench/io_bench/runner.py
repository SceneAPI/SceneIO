"""O0-O5 I/O benchmark harness for docs/io_optimization_plan.md.

Measures, per codec, encode (write) + decode (read) throughput (MB/s over the raw
payload) and peak Python allocation (tracemalloc), for sceneio._core vs the oracle
library where one exists, on representative payloads for all 71 codecs. Read
measurements retain the legacy whole-file bytes/copy-decode path beside the
public registry mmap path, so their peak delta captures the input copy O1
removes and, for NPY/FLO, the decoded-array copy O2 removes. Write measurements
retain the in-memory bytes encoder beside the public file sink, so their peak
delta captures the output-sized Python allocation O3 removes. Ordinary runs
render unavailable comparisons as "-"; strict qualification requires every
declared comparison and propagates provider failures.

Run: python bench/bench_io.py [--runs N] [--scale S] [--cold-cache]
Synthetic fixtures are generated in a temporary directory and never committed.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sqlite3
import sys
import tempfile
from functools import partial
from pathlib import Path

import numpy as np

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import sceneio
from bench.io_bench import measure as benchmark_measure
from bench.io_bench.families import (
    reconstruction as reconstruction_family,
)
from bench.io_bench.families import sequences as sequence_family
from bench.io_bench.families import splats as splat_family
from bench.io_bench.families.arrays import build_array_specs
from bench.io_bench.families.calibration import (
    build_calibration_specs,
)
from bench.io_bench.families.common import _record_nbytes
from bench.io_bench.families.containers import build_container_specs
from bench.io_bench.families.dense import build_dense_specs
from bench.io_bench.families.images import build_image_specs
from bench.io_bench.families.media import build_media_path_specs
from bench.io_bench.families.meshes import build_mesh_specs
from bench.io_bench.families.points import build_point_specs
from bench.io_bench.fixtures import arrays as array_fixtures
from bench.io_bench.fixtures import (
    calibration as calibration_fixtures,
)
from bench.io_bench.fixtures import images as image_fixtures
from bench.io_bench.fixtures import meshes as mesh_fixtures
from bench.io_bench.fixtures import points as point_fixtures
from bench.io_bench.fixtures import (
    reconstruction as reconstruction_fixtures,
)
from bench.io_bench.fixtures import sequences as sequence_fixtures
from bench.io_bench.fixtures import splats as splat_fixtures
from bench.io_bench.fixtures.containers import _ncore_directory_fixture
from bench.io_bench.model import DirectorySpec
from bench.io_bench.model import PathSpec as PathSpec
from bench.io_bench.model import Spec as Spec
from bench.io_bench.oracles import arrays as array_oracles
from bench.io_bench.oracles import (
    calibration as calibration_oracles,
)
from bench.io_bench.oracles import images as image_oracles
from bench.io_bench.oracles import meshes as mesh_oracles
from bench.io_bench.oracles import points as point_oracles
from bench.io_bench.oracles import (
    reconstruction as reconstruction_oracles,
)
from bench.io_bench.oracles import sequences as sequence_oracles
from bench.io_bench.oracles import splats as splat_oracles
from bench.io_bench.reporting import (
    print_cold_cache_unavailable,
    print_colmap_db_row,
    print_directory_row,
    print_encoding_variants,
    print_json_result,
    print_path_row,
    print_primary_error,
    print_primary_header,
    print_primary_row,
    print_regression_guard_passed,
    print_summary,
    print_typed_adapter,
)
from sceneio import _core

_depth_map = array_fixtures._depth_map
_dmb_oracle_read = array_oracles._dmb_oracle_read
_dmb_oracle_write = array_oracles._dmb_oracle_write
_load_npz_oracle = array_oracles._load_npz_oracle
_np_r = array_oracles._np_r
_np_w = array_oracles._np_w
_save_npz_oracle = array_oracles._save_npz_oracle
safetensors_load = array_oracles.safetensors_load
safetensors_load_file = array_oracles.safetensors_load_file
safetensors_open = array_oracles.safetensors_open
safetensors_save = array_oracles.safetensors_save
safetensors_save_file = array_oracles.safetensors_save_file

_kalibr_calibration = calibration_fixtures._kalibr_calibration
_single_calibration = calibration_fixtures._single_calibration
_xml_oracle_read = calibration_oracles._xml_oracle_read
_xml_oracle_write = calibration_oracles._xml_oracle_write
_yaml_oracle_read = calibration_oracles._yaml_oracle_read
_yaml_oracle_write = calibration_oracles._yaml_oracle_write
yaml = calibration_oracles.yaml

_img_f32 = image_fixtures._img_f32
_img_u8 = image_fixtures._img_u8
_img_webp_palette = image_fixtures._img_webp_palette
_imageio_r = image_oracles._imageio_r
_imageio_w = image_oracles._imageio_w
_openexr_r = image_oracles._openexr_r
_openexr_w = image_oracles._openexr_w
_pil_r = image_oracles._pil_r
_pil_w = image_oracles._pil_w
iio = image_oracles.iio
OpenEXR = image_oracles.OpenEXR
PILImage = image_oracles.PILImage

_mesh_obj = mesh_fixtures._mesh_obj
_mesh_off = mesh_fixtures._mesh_off
_mesh_ply = mesh_fixtures._mesh_ply
_mesh_scene = mesh_fixtures._mesh_scene
_mesh_stl = mesh_fixtures._mesh_stl
_trimesh_glb_r = mesh_oracles._trimesh_glb_r
_trimesh_glb_w = mesh_oracles._trimesh_glb_w
_trimesh_gltf_r = mesh_oracles._trimesh_gltf_r
_trimesh_gltf_w = mesh_oracles._trimesh_gltf_w
_trimesh_obj_r = mesh_oracles._trimesh_obj_r
_trimesh_obj_w = mesh_oracles._trimesh_obj_w
_trimesh_off_r = mesh_oracles._trimesh_off_r
_trimesh_off_w = mesh_oracles._trimesh_off_w
_trimesh_ply_r = mesh_oracles._trimesh_ply_r
_trimesh_ply_w = mesh_oracles._trimesh_ply_w
_trimesh_stl_r = mesh_oracles._trimesh_stl_r
_trimesh_stl_w = mesh_oracles._trimesh_stl_w
trimesh = mesh_oracles.trimesh

_pc = point_fixtures._pc
_pc_laz = point_fixtures._pc_laz
_pc_ply = point_fixtures._pc_ply
_laspy_laz_w = point_oracles._laspy_laz_w
_laspy_r = point_oracles._laspy_r
_laspy_w = point_oracles._laspy_w
_open3d_pcd_r = point_oracles._open3d_pcd_r
_open3d_pcd_w = point_oracles._open3d_pcd_w
_open3d_ply_r = point_oracles._open3d_ply_r
_open3d_ply_w = point_oracles._open3d_ply_w
_pts_oracle_read = point_oracles._pts_oracle_read
_pts_oracle_write = point_oracles._pts_oracle_write
laspy = point_oracles.laspy
o3d = point_oracles.o3d

_bal_payload_nbytes = reconstruction_family._bal_payload_nbytes
_euroc_payload_nbytes = reconstruction_family._euroc_payload_nbytes
_g2o_payload_nbytes = reconstruction_family._g2o_payload_nbytes
build_reconstruction_specs = (
    reconstruction_family.build_reconstruction_specs
)
_bal_fixture = reconstruction_fixtures._bal_fixture
_euroc_fixture = reconstruction_fixtures._euroc_fixture
_g2o_fixture = reconstruction_fixtures._g2o_fixture
_poses_and_reconstruction = (
    reconstruction_fixtures._poses_and_reconstruction
)
_EUROC_HEADER = reconstruction_oracles._EUROC_HEADER
_bal_oracle_read = reconstruction_oracles._bal_oracle_read
_bal_oracle_write = reconstruction_oracles._bal_oracle_write
_euroc_oracle_read = reconstruction_oracles._euroc_oracle_read
_euroc_oracle_write = reconstruction_oracles._euroc_oracle_write
_g2o_oracle_read = reconstruction_oracles._g2o_oracle_read
_g2o_oracle_write = reconstruction_oracles._g2o_oracle_write

build_sequence_specs = sequence_family.build_sequence_specs
_image_sequence_directory_fixture = (
    sequence_fixtures._image_sequence_directory_fixture
)
_apng_fixture = sequence_fixtures._apng_fixture
_animated_webp_fixture = sequence_fixtures._animated_webp_fixture
_y4m_fixture = sequence_fixtures._y4m_fixture
_webm_fixture = sequence_fixtures._webm_fixture
_theora_fixture = sequence_fixtures._theora_fixture
_apng_oracle_read = sequence_oracles._apng_oracle_read
_apng_oracle_write = sequence_oracles._apng_oracle_write
_animated_webp_oracle_read = sequence_oracles._animated_webp_oracle_read
_animated_webp_oracle_write = sequence_oracles._animated_webp_oracle_write
_y4m_oracle_read = sequence_oracles._y4m_oracle_read
_y4m_oracle_write = sequence_oracles._y4m_oracle_write
_webm_oracle_read = sequence_oracles._webm_oracle_read
_webm_oracle_write = sequence_oracles._webm_oracle_write

build_splat_specs = splat_family.build_splat_specs
_gauss = splat_fixtures._gauss
_gsply_ply_r = splat_oracles._gsply_ply_r
_gsply_ply_w = splat_oracles._gsply_ply_w
_gsply_spz_r = splat_oracles._gsply_spz_r
_gsply_spz_w = splat_oracles._gsply_spz_w
gsply = splat_oracles.gsply

_measure = benchmark_measure.measure
_measure_in_process_rss = benchmark_measure.measure_in_process_rss
_try = benchmark_measure.try_measure

_COLMAP_PAIR_MULTIPLIER = 2_147_483_647


def _colmap_db_fixture(scale, profile="sceneio-hybrid-v1"):
    image_count = 64
    feature_count = max(1, int(1024 * scale))
    match_count = min(feature_count, max(1, int(256 * scale)))
    descriptor_columns = 128
    camera = _core.camera(
        1,
        1,
        1920,
        1080,
        np.array([1200.0, 1200.0, 960.0, 540.0], np.float64),
    )
    keypoints = np.empty((feature_count, 4), np.float32)
    indices = np.arange(feature_count, dtype=np.float32)
    keypoints[:, 0] = np.remainder(indices * 17.0, 1920.0)
    keypoints[:, 1] = np.remainder(indices * 29.0, 1080.0)
    keypoints[:, 2] = 1.0 + np.remainder(indices, 8.0) * 0.125
    keypoints[:, 3] = np.remainder(indices * 0.01, 2.0 * np.pi)
    descriptor_template = np.arange(
        feature_count * descriptor_columns, dtype=np.uint32
    ).reshape(feature_count, descriptor_columns)
    features = [
        _core.feature_set(
            keypoints,
            np.asarray(
                descriptor_template + image_id * 31,
                dtype=np.uint8,
            ),
            image_id=image_id,
            image_name=f"images/frame_{image_id:06d}.jpg",
            camera_id=1,
            image_size=(1920, 1080),
            extractor_type=0,
        )
        for image_id in range(1, image_count + 1)
    ]
    image_pairs = np.column_stack(
        (
            np.arange(1, image_count, dtype=np.uint32),
            np.arange(2, image_count + 1, dtype=np.uint32),
        )
    )
    pair_count = len(image_pairs)
    one_pair = np.column_stack(
        (
            np.arange(match_count, dtype=np.uint32),
            np.arange(match_count, dtype=np.uint32),
        )
    )
    matches = np.tile(one_pair, (pair_count, 1))
    match_offsets = np.arange(
        0, (pair_count + 1) * match_count, match_count, dtype=np.uint64
    )
    verified_count = max(1, match_count // 2)
    verified_matches = np.tile(one_pair[:verified_count], (pair_count, 1))
    verified_offsets = np.arange(
        0,
        (pair_count + 1) * verified_count,
        verified_count,
        dtype=np.uint64,
    )
    identity = np.tile(np.eye(3, dtype=np.float64), (pair_count, 1, 1))
    qvecs = np.zeros((pair_count, 4), np.float64)
    qvecs[:, 0] = 1.0
    tvecs = np.zeros((pair_count, 3), np.float64)
    tvecs[:, 0] = np.arange(pair_count, dtype=np.float64) * 0.01
    present = np.ones(pair_count, np.uint8)
    graph = _core.match_graph(
        image_pairs,
        match_offsets,
        matches,
        verified_offsets,
        verified_matches,
        configs=np.full(pair_count, 2, np.int32),
        fundamental_matrices=identity,
        fundamental_present=present,
        essential_matrices=identity,
        essential_present=present,
        homographies=identity,
        homography_present=present,
        qvecs=qvecs,
        tvecs=tvecs,
        pose_present=present,
        match_present=present,
        geometry_present=present,
    )
    ownership = (
        _core.colmap_maxx_schema_info(
            1,
            1,
            "SceneIO benchmark",
            "sceneio-owned-benchmark",
        )
        if profile == "maxx-v1"
        else None
    )
    return _core.colmap_database(
        [camera],
        features,
        graph,
        prior_focal_length=np.array([1], np.uint8),
        maxx_schema_info=ownership,
    )


def _colmap_db_payload_nbytes(value):
    total = sum(np.asarray(camera.params).nbytes for camera in value.cameras)
    total += np.asarray(value.prior_focal_length).nbytes
    for index in range(value.num_images):
        feature = value.feature_at(index)
        total += np.asarray(feature.keypoints).nbytes
        if feature.descriptors is not None:
            total += np.asarray(feature.descriptors).nbytes
        if feature.scores is not None:
            total += np.asarray(feature.scores).nbytes
    graph = value.match_graph
    for name in (
        "image_pairs",
        "match_offsets",
        "matches",
        "verified_offsets",
        "verified_matches",
        "configs",
        "fundamental_matrices",
        "essential_matrices",
        "homographies",
        "qvecs",
        "tvecs",
    ):
        total += np.asarray(getattr(graph, name)).nbytes
    return total


def _colmap_blob(value):
    return memoryview(np.asarray(value)).cast("B")


def _sqlite_reference_write_colmap_db(value, path):
    destination = Path(path)
    destination.unlink(missing_ok=True)
    connection = sqlite3.connect(destination)
    try:
        connection.executescript(
            """
            CREATE TABLE cameras(
              camera_id INTEGER PRIMARY KEY NOT NULL,
              model INTEGER NOT NULL,
              width INTEGER NOT NULL,
              height INTEGER NOT NULL,
              params BLOB,
              prior_focal_length INTEGER NOT NULL);
            CREATE TABLE images(
              image_id INTEGER PRIMARY KEY NOT NULL,
              name TEXT NOT NULL UNIQUE,
              camera_id INTEGER NOT NULL,
              time_id INTEGER);
            CREATE TABLE keypoints(
              image_id INTEGER PRIMARY KEY NOT NULL,
              rows INTEGER NOT NULL,
              cols INTEGER NOT NULL,
              data BLOB);
            CREATE TABLE descriptors(
              image_id INTEGER PRIMARY KEY NOT NULL,
              type INTEGER NOT NULL,
              rows INTEGER NOT NULL,
              cols INTEGER NOT NULL,
              data BLOB);
            CREATE TABLE matches(
              pair_id INTEGER PRIMARY KEY NOT NULL,
              rows INTEGER NOT NULL,
              cols INTEGER NOT NULL,
              data BLOB);
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
              tvec BLOB);
            """
        )
        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
            "INSERT INTO cameras VALUES(?,?,?,?,?,?)",
            (
                (
                    camera.id,
                    camera.model_id,
                    camera.width,
                    camera.height,
                    _colmap_blob(camera.params),
                    int(value.prior_focal_length[index]),
                )
                for index, camera in enumerate(value.cameras)
            ),
        )
        image_rows = []
        keypoint_rows = []
        descriptor_rows = []
        for index in range(value.num_images):
            feature = value.feature_at(index)
            image_rows.append(
                (
                    feature.image_id,
                    feature.image_name,
                    feature.camera_id,
                    feature.time_id,
                )
            )
            if feature.keypoints_present:
                keypoint_rows.append(
                    (
                        feature.image_id,
                        feature.num_keypoints,
                        feature.keypoint_columns,
                        _colmap_blob(feature.keypoints),
                    )
                )
            if feature.descriptors is not None:
                descriptor_rows.append(
                    (
                        feature.image_id,
                        feature.extractor_type,
                        feature.num_keypoints,
                        feature.descriptor_dim,
                        _colmap_blob(feature.descriptors),
                    )
                )
        connection.executemany(
            "INSERT INTO images VALUES(?,?,?,?)", image_rows
        )
        connection.executemany(
            "INSERT INTO keypoints VALUES(?,?,?,?)", keypoint_rows
        )
        connection.executemany(
            "INSERT INTO descriptors VALUES(?,?,?,?,?)", descriptor_rows
        )
        graph = value.match_graph
        match_rows = []
        geometry_rows = []
        for pair in range(graph.num_pairs):
            pair_id = int(graph.pair_ids[pair])
            match_begin = int(graph.match_offsets[pair])
            match_end = int(graph.match_offsets[pair + 1])
            if graph.match_present[pair]:
                match_rows.append(
                    (
                        pair_id,
                        match_end - match_begin,
                        2,
                        _colmap_blob(
                            graph.matches[match_begin:match_end]
                        ),
                    )
                )
            verified_begin = int(graph.verified_offsets[pair])
            verified_end = int(graph.verified_offsets[pair + 1])
            if graph.geometry_present[pair]:
                geometry_rows.append(
                    (
                        pair_id,
                        verified_end - verified_begin,
                        2,
                        _colmap_blob(
                            graph.verified_matches[
                                verified_begin:verified_end
                            ]
                        ),
                        int(graph.configs[pair]),
                        _colmap_blob(graph.fundamental_matrices[pair]),
                        _colmap_blob(graph.essential_matrices[pair]),
                        _colmap_blob(graph.homographies[pair]),
                        _colmap_blob(graph.qvecs[pair]),
                        _colmap_blob(graph.tvecs[pair]),
                    )
                )
        connection.executemany(
            "INSERT INTO matches VALUES(?,?,?,?)", match_rows
        )
        connection.executemany(
            "INSERT INTO two_view_geometries VALUES(?,?,?,?,?,?,?,?,?,?)",
            geometry_rows,
        )
        connection.execute(f"PRAGMA user_version={value.user_version}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _sqlite_reference_query(path, statements):
    connection = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        return tuple(
            connection.execute(statement, parameters).fetchall()
            for statement, parameters in statements
        )
    finally:
        connection.close()


def _sqlite_reference_read_colmap_db(path):
    return _sqlite_reference_query(
        path,
        (
            ("SELECT * FROM cameras ORDER BY camera_id", ()),
            ("SELECT * FROM images ORDER BY image_id", ()),
            ("SELECT * FROM keypoints ORDER BY image_id", ()),
            ("SELECT * FROM descriptors ORDER BY image_id", ()),
            ("SELECT * FROM matches ORDER BY pair_id", ()),
            (
                "SELECT * FROM two_view_geometries ORDER BY pair_id",
                (),
            ),
        ),
    )


def _sqlite_reference_inspect_colmap_db(path):
    return _sqlite_reference_query(
        path,
        (
            ("SELECT count(*) FROM cameras", ()),
            ("SELECT count(*) FROM images", ()),
            ("SELECT coalesce(sum(rows),0) FROM keypoints", ()),
            ("SELECT coalesce(sum(rows),0) FROM descriptors", ()),
            ("SELECT coalesce(sum(rows),0) FROM matches", ()),
            (
                "SELECT coalesce(sum(rows),0) "
                "FROM two_view_geometries",
                (),
            ),
            (
                "SELECT image_id,name,camera_id,time_id "
                "FROM images ORDER BY image_id",
                (),
            ),
            (
                "SELECT image_id,rows,cols "
                "FROM keypoints ORDER BY image_id",
                (),
            ),
            (
                "SELECT image_id,type,rows,cols "
                "FROM descriptors ORDER BY image_id",
                (),
            ),
        ),
    )


def _sqlite_reference_read_colmap_db_image(path, image_id):
    return _sqlite_reference_query(
        path,
        (
            (
                "SELECT * FROM images WHERE image_id=?",
                (image_id,),
            ),
            (
                "SELECT * FROM keypoints WHERE image_id=?",
                (image_id,),
            ),
            (
                "SELECT * FROM descriptors WHERE image_id=?",
                (image_id,),
            ),
        ),
    )


def _sqlite_reference_read_colmap_db_pair(path, image_id1, image_id2):
    low, high = sorted((image_id1, image_id2))
    pair_id = low * _COLMAP_PAIR_MULTIPLIER + high
    return _sqlite_reference_query(
        path,
        (
            ("SELECT * FROM matches WHERE pair_id=?", (pair_id,)),
            (
                "SELECT * FROM two_view_geometries WHERE pair_id=?",
                (pair_id,),
            ),
        ),
    )


def _assert_colmap_db_equal(actual, expected):
    if actual.profile == expected.profile:
        assert actual.user_version == expected.user_version
    assert len(actual.cameras) == len(expected.cameras)
    for left, right in zip(actual.cameras, expected.cameras, strict=True):
        assert (
            left.id,
            left.model_id,
            left.width,
            left.height,
        ) == (
            right.id,
            right.model_id,
            right.width,
            right.height,
        )
        np.testing.assert_array_equal(left.params, right.params)
    np.testing.assert_array_equal(
        actual.prior_focal_length, expected.prior_focal_length
    )
    assert actual.num_images == expected.num_images
    for index in range(actual.num_images):
        left = actual.feature_at(index)
        right = expected.feature_at(index)
        assert (
            left.image_id,
            left.image_name,
            left.camera_id,
            tuple(left.image_size),
            left.time_id,
            left.extractor_type,
            left.keypoints_present,
        ) == (
            right.image_id,
            right.image_name,
            right.camera_id,
            tuple(right.image_size),
            right.time_id,
            right.extractor_type,
            right.keypoints_present,
        )
        np.testing.assert_array_equal(left.keypoints, right.keypoints)
        if left.descriptors is None or right.descriptors is None:
            assert left.descriptors is right.descriptors
        else:
            np.testing.assert_array_equal(
                left.descriptors, right.descriptors
            )
    left_graph = actual.match_graph
    right_graph = expected.match_graph
    for name in (
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
    ):
        np.testing.assert_array_equal(
            getattr(left_graph, name), getattr(right_graph, name)
        )


def _evict_file_cache(path):
    """Best-effort cold-cache hint (effective where POSIX_FADV_DONTNEED exists)."""
    path = Path(path)
    if path.is_dir():
        results = [
            _evict_file_cache(item)
            for item in path.rglob("*")
            if item.is_file()
        ]
        return any(results)
    if not hasattr(os, "posix_fadvise") or not hasattr(os, "POSIX_FADV_DONTNEED"):
        return False
    with open(path, "rb") as stream:
        os.posix_fadvise(stream.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
    return True


def _stored_size(path) -> int:
    """Return encoded bytes for either a file or directory-backed container."""

    path = Path(path)
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _specs(scale, pose_bundle=None):
    image_specs = build_image_specs(scale)
    sequence_specs = build_sequence_specs(scale)
    mesh_specs = build_mesh_specs(scale)
    point_specs = build_point_specs(scale)
    splat_specs = build_splat_specs(scale)
    reconstruction_specs = build_reconstruction_specs(
        scale, pose_bundle
    )
    return [
        *image_specs[:5],
        *sequence_specs,
        *image_specs[5:],
        *point_specs[:3],
        *mesh_specs,
        *point_specs[3:],
        *splat_specs,
        *build_array_specs(scale),
        *reconstruction_specs[:4],
        *build_calibration_specs(scale),
        *reconstruction_specs[4:],
        *build_dense_specs(scale),
    ]


def _directory_specs(reconstruction, scale, root):
    if (
        reconstruction is not None
        and not reconstruction.has_rig_frame_model
    ):
        reconstruction = (
            reconstruction_fixtures._modern_colmap_reconstruction(
                reconstruction
            )
        )
    return [
        DirectorySpec(
            "colmap_sparse",
            lambda: (reconstruction, reconstruction),
            _core.write_colmap_sparse,
            _core.read_colmap_sparse,
            lambda record, payload: _record_nbytes(payload),
        ),
        DirectorySpec(
            "colmap_sparse_txt",
            lambda: (reconstruction, reconstruction),
            _core.write_colmap_txt,
            _core.read_colmap_txt,
            lambda record, payload: _record_nbytes(payload),
        ),
        DirectorySpec(
            "ncore_v4",
            partial(
                _ncore_directory_fixture,
                root,
                scale,
            ),
            lambda value, path: sceneio.write(
                value, path, format="ncore_v4"
            ),
            sceneio.materialize_ncore_v4,
            lambda record, payload: payload,
            path_read=sceneio.materialize_ncore_v4,
            partial=lambda path: sceneio.read_ncore_component(
                path,
                sceneio.NCoreSelection(
                    "point_clouds",
                    "lidar",
                    frames=(8, 9),
                ),
            ),
            assert_read=_assert_ncore_dataset_equal,
            assert_partial=_assert_ncore_partial_equal,
        ),
        DirectorySpec(
            "rtmv",
            partial(
                sequence_fixtures._rtmv_directory_fixture,
                root,
                scale,
            ),
            None,
            lambda path: sceneio.read(path, format="rtmv"),
            lambda record, payload: payload,
        ),
        DirectorySpec(
            "image_sequence",
            partial(
                _image_sequence_directory_fixture,
                root,
                scale,
            ),
            lambda value, path: sceneio.write(
                value, path, format="image_sequence"
            ),
            lambda path: sceneio.read(
                path, format="image_sequence"
            ),
            lambda record, payload: payload,
        ),
    ]


def _directory_size(path):
    return sum(
        entry.stat().st_size
        for entry in Path(path).rglob("*")
        if entry.is_file()
    )


def _assert_ncore_dataset_equal(expected, actual):
    assert expected.sequence_id == actual.sequence_id
    assert expected.timestamp_interval_us == actual.timestamp_interval_us
    assert expected.generic_metadata == actual.generic_metadata
    assert len(expected.components) == len(actual.components)
    for left, right in zip(expected.components, actual.components, strict=True):
        assert left.component.id == right.component.id
        assert left.component.group == right.component.group
        assert set(left.arrays) == set(right.arrays)
        for name in sorted(left.arrays):
            np.testing.assert_array_equal(left.arrays[name], right.arrays[name])


def _assert_ncore_partial_equal(expected, actual):
    source = expected.components[0]
    assert actual.selected_items == ("8",)
    np.testing.assert_array_equal(
        actual.array("pc_timestamps_us"),
        source.array("pc_timestamps_us")[8:9],
    )
    np.testing.assert_array_equal(
        actual.array("pcs/8/xyz"),
        source.array("pcs/8/xyz"),
    )
    assert tuple(actual.arrays) == ("pc_timestamps_us", "pcs/8/xyz")


def _partial_request(codec_id, info, full_record=None):
    if codec_id in {"gltf", "glb"}:
        return {"primitive_id": 0}
    if codec_id in {"ply_mesh", "stl", "off"}:
        faces = info.metadata["num_faces"]
        if faces == 0:
            return None
        selected = max(1, faces // 16)
        start = (faces - selected) // 2
        return {"faces": (start, start + selected)}
    if codec_id in {
        "pfm",
        "netpbm",
        "webp",
        "flo",
        "dmb",
        "colmap_mvs_depth",
        "colmap_mvs_normal",
    }:
        height, width = info.shape[:2]
        out_height = max(1, height // 8)
        out_width = max(1, width // 8)
        row_start = (height - out_height) // 2
        col_start = (width - out_width) // 2
        return {
            "window": (
                row_start,
                row_start + out_height,
                col_start,
                col_start + out_width,
            )
        }
    if codec_id in {
        "xyz",
        "pts",
        "ply",
        "pcd",
        "las",
        "laz",
        "gaussian_ply",
        "compressed_ply",
        "sog",
        "ksplat",
        "splat",
    }:
        selected = max(1, info.count // 16)
        start = (info.count - selected) // 2
        return {"points": (start, start + selected)}
    if codec_id in {"colmap_sparse", "colmap_sparse_txt"}:
        image_ids = np.asarray(full_record.image_ids)
        return {"image_id": int(image_ids[len(image_ids) // 2])}
    if codec_id in {"image_sequence", "rtmv", "y4m", "webm", "theora"}:
        selected = max(1, info.count // 16)
        start = (info.count - selected) // 2
        return {"frames": (start, start + selected)}
    if codec_id == "safetensors":
        return {"tensors": ("b",)}
    if codec_id == "euroc_state":
        selected = max(1, info.count // 16)
        start = (info.count - selected) // 2
        return {"states": (start, start + selected)}
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=7)
    ap.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="multiply logical payload sizes (e.g. 32 for generated large fixtures)",
    )
    ap.add_argument(
        "--cold-cache",
        action="store_true",
        help="request POSIX_FADV_DONTNEED before each path read when supported",
    )
    ap.add_argument(
        "--only",
        action="append",
        metavar="FORMAT",
        help=(
            "benchmark only this registered format id; repeat for multiple "
            "formats (the default remains the complete codec sweep)"
        ),
    )
    ap.add_argument(
        "--skip-oracles",
        action="store_true",
        help="skip independent-library timing while retaining SceneIO verification",
    )
    ap.add_argument(
        "--strict-oracles",
        action="store_true",
        help=(
            "require the complete built-in sweep and every declared timed "
            "comparison provider; propagate comparison failures"
        ),
    )
    ap.add_argument(
        "--large-safetensors-mib",
        type=int,
        default=0,
        help=(
            "run only the generated safetensors full/inspect/single-tensor/"
            "stream-write fixture at this MiB size (use 128 or 1024)"
        ),
    )
    ap.add_argument(
        "--colmap-db-profile",
        choices=(
            "sceneio-hybrid-v1",
            "colmap-3.13.0",
            "colmap-4.1.1",
            "colmap-main-64805cb870b5",
            "maxx-v1",
        ),
        default="sceneio-hybrid-v1",
        help="COLMAP SQLite schema used by the colmap_db benchmark",
    )
    ap.add_argument(
        "--require-o4-gains",
        action="store_true",
        help=(
            "fail unless stable high-signal O4 controls improve and mmap/sink "
            "traced allocations remain bounded"
        ),
    )
    ap.add_argument(
        "--require-o5-inspect-gains",
        action="store_true",
        help="fail unless stable metadata-only inspections beat full reads",
    )
    ap.add_argument(
        "--require-o5-partial-gains",
        action="store_true",
        help="fail unless stable partial reads beat full record materialization",
    )
    ap.add_argument("--json", type=Path, help="write machine-readable results to this path")
    args = ap.parse_args()
    if args.scale <= 0:
        ap.error("--scale must be positive")
    if args.large_safetensors_mib < 0:
        ap.error("--large-safetensors-mib must be non-negative")
    if args.only and (
        args.require_o4_gains
        or args.require_o5_inspect_gains
        or args.require_o5_partial_gains
    ):
        ap.error("--only cannot be combined with complete-sweep regression guards")
    if args.only and args.large_safetensors_mib:
        ap.error("--only cannot be combined with --large-safetensors-mib")
    if args.strict_oracles and args.skip_oracles:
        ap.error("--strict-oracles cannot be combined with --skip-oracles")
    if args.strict_oracles and args.only:
        ap.error("--strict-oracles cannot be combined with --only")
    if args.strict_oracles and args.large_safetensors_mib:
        ap.error(
            "--strict-oracles cannot be combined with --large-safetensors-mib"
        )
    with tempfile.TemporaryDirectory(prefix="sceneio_bench_") as tmp:
        if args.large_safetensors_mib:
            failures, results = _run_large_safetensors(args, tmp)
        else:
            failures, results = _run_benchmark(args, tmp)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    if failures:
        raise RuntimeError("benchmark failures: " + ", ".join(failures))


def _run_large_safetensors(args, tmp):
    size_bytes = args.large_safetensors_mib * 1024 * 1024
    count = max(1, size_bytes // np.dtype(np.float32).itemsize)
    large = np.arange(count, dtype=np.float32)
    small = np.arange(1024, dtype=np.int16)
    arrays = {"large": large, "small": small}
    record = _core.tensor_dict(arrays, {"fixture": "generated"})
    path = Path(tmp) / "large.safetensors"
    oracle_path = Path(tmp) / "large-oracle.safetensors"

    def write_sceneio():
        sceneio.write(record, path, format="safetensors")

    write_time, write_peak = _measure(write_sceneio, args.runs)
    write_rss = _measure_in_process_rss(write_sceneio)

    def full_read():
        if args.cold_cache:
            _evict_file_cache(path)
        return sceneio.read(path, format="safetensors")

    def inspect_read():
        if args.cold_cache:
            _evict_file_cache(path)
        return sceneio.inspect(path, format="safetensors")

    def selected_read():
        if args.cold_cache:
            _evict_file_cache(path)
        return sceneio.read_partial(
            path, format="safetensors", tensors=("small",)
        )

    full_time, full_peak = _measure(full_read, args.runs)
    full_rss = _measure_in_process_rss(full_read)
    inspect_time, inspect_peak = _measure(inspect_read, args.runs)
    inspect_rss = _measure_in_process_rss(inspect_read)
    selected_time, selected_peak = _measure(selected_read, args.runs)
    selected_rss = _measure_in_process_rss(selected_read)

    oracle_metrics = {}
    if (
        safetensors_save_file
        and safetensors_load_file
        and safetensors_open
        and not args.skip_oracles
    ):
        def oracle_full():
            if args.cold_cache:
                _evict_file_cache(path)
            return safetensors_load_file(path)

        oracle_write_time, oracle_write_peak = _measure(
            lambda: safetensors_save_file(arrays, oracle_path), args.runs
        )
        oracle_write_rss = _measure_in_process_rss(
            lambda: safetensors_save_file(arrays, oracle_path)
        )
        oracle_full_time, oracle_full_peak = _measure(
            oracle_full, args.runs
        )
        oracle_full_rss = _measure_in_process_rss(oracle_full)

        def oracle_inspect():
            if args.cold_cache:
                _evict_file_cache(path)
            with safetensors_open(path, framework="np") as handle:
                return tuple(
                    (
                        name,
                        tuple(handle.get_slice(name).get_shape()),
                        handle.get_slice(name).get_dtype(),
                    )
                    for name in tuple(handle.keys())
                )

        def oracle_selected():
            if args.cold_cache:
                _evict_file_cache(path)
            with safetensors_open(path, framework="np") as handle:
                return handle.get_tensor("small")

        oracle_inspect_time, oracle_inspect_peak = _measure(
            oracle_inspect, args.runs
        )
        oracle_inspect_rss = _measure_in_process_rss(oracle_inspect)
        oracle_selected_time, oracle_selected_peak = _measure(
            oracle_selected, args.runs
        )
        oracle_selected_rss = _measure_in_process_rss(oracle_selected)
        oracle_metrics = {
            "oracle_write_ms": oracle_write_time * 1000,
            "oracle_write_peak_mb": oracle_write_peak / 1e6,
            "oracle_write_rss_mb": oracle_write_rss / 1e6,
            "oracle_full_ms": oracle_full_time * 1000,
            "oracle_full_peak_mb": oracle_full_peak / 1e6,
            "oracle_full_rss_mb": oracle_full_rss / 1e6,
            "oracle_inspect_ms": oracle_inspect_time * 1000,
            "oracle_inspect_peak_mb": oracle_inspect_peak / 1e6,
            "oracle_inspect_rss_mb": oracle_inspect_rss / 1e6,
            "oracle_selected_ms": oracle_selected_time * 1000,
            "oracle_selected_peak_mb": oracle_selected_peak / 1e6,
            "oracle_selected_rss_mb": oracle_selected_rss / 1e6,
        }

    decoded = full_read()
    selected = selected_read()
    np.testing.assert_array_equal(decoded["small"], small)
    np.testing.assert_array_equal(selected["small"], small)
    inspected = {array.name: array for array in inspect_read().arrays}
    assert inspected["large"].shape == large.shape
    del decoded, selected
    gc.collect()

    result = {
        "codec": "safetensors-large",
        "fixture_mib": args.large_safetensors_mib,
        "file_mb": path.stat().st_size / 1e6,
        "write_ms": write_time * 1000,
        "write_peak_mb": write_peak / 1e6,
        "write_rss_mb": write_rss / 1e6,
        "full_ms": full_time * 1000,
        "full_peak_mb": full_peak / 1e6,
        "full_rss_mb": full_rss / 1e6,
        "inspect_ms": inspect_time * 1000,
        "inspect_peak_mb": inspect_peak / 1e6,
        "inspect_rss_mb": inspect_rss / 1e6,
        "selected_ms": selected_time * 1000,
        "selected_peak_mb": selected_peak / 1e6,
        "selected_rss_mb": selected_rss / 1e6,
        **oracle_metrics,
    }
    print_json_result(result)
    return [], [result]


def _benchmark_colmap_db(args, tmp):
    value = _colmap_db_fixture(
        args.scale, args.colmap_db_profile
    )
    native_path = Path(tmp) / "colmap-database.db"
    oracle_path = Path(tmp) / "colmap-database-oracle.db"
    payload_bytes = _colmap_db_payload_nbytes(value)
    payload_mb = payload_bytes / 1e6
    selected_image_id = value.feature_at(value.num_images // 2).image_id
    selected_pair = tuple(
        int(item)
        for item in value.match_graph.image_pairs[
            value.match_graph.num_pairs // 2
        ]
    )

    def native_write():
        return sceneio.write(
            value,
            native_path,
            format="colmap_db",
            profile=(
                None
                if args.colmap_db_profile ==
                "sceneio-hybrid-v1"
                else args.colmap_db_profile
            ),
        )

    def oracle_write():
        return _sqlite_reference_write_colmap_db(value, oracle_path)

    native_write_time, native_write_peak = _measure(
        native_write, args.runs
    )
    native_write_rss = _measure_in_process_rss(native_write)
    oracle_write_time = oracle_write_peak = oracle_write_rss = None
    if not args.skip_oracles:
        oracle_write_time, oracle_write_peak = _measure(
            oracle_write, args.runs
        )
        oracle_write_rss = _measure_in_process_rss(oracle_write)

    def native_full_read():
        if args.cold_cache:
            _evict_file_cache(native_path)
        return sceneio.read(native_path, format="colmap_db")

    def oracle_full_read():
        if args.cold_cache:
            _evict_file_cache(native_path)
        return _sqlite_reference_read_colmap_db(native_path)

    def native_inspect():
        if args.cold_cache:
            _evict_file_cache(native_path)
        return sceneio.inspect(native_path, format="colmap_db")

    def oracle_inspect():
        if args.cold_cache:
            _evict_file_cache(native_path)
        return _sqlite_reference_inspect_colmap_db(native_path)

    def native_image_read():
        if args.cold_cache:
            _evict_file_cache(native_path)
        return sceneio.read_partial(
            native_path,
            format="colmap_db",
            image_id=selected_image_id,
        )

    def oracle_image_read():
        if args.cold_cache:
            _evict_file_cache(native_path)
        return _sqlite_reference_read_colmap_db_image(
            native_path, selected_image_id
        )

    def native_pair_read():
        if args.cold_cache:
            _evict_file_cache(native_path)
        return sceneio.read_partial(
            native_path,
            format="colmap_db",
            pair=selected_pair,
        )

    def oracle_pair_read():
        if args.cold_cache:
            _evict_file_cache(native_path)
        return _sqlite_reference_read_colmap_db_pair(
            native_path, *selected_pair
        )

    native_full_time, native_full_peak = _measure(
        native_full_read, args.runs
    )
    native_full_rss = _measure_in_process_rss(native_full_read)
    inspect_time, inspect_peak = _measure(native_inspect, args.runs)
    inspect_rss = _measure_in_process_rss(native_inspect)
    image_time, image_peak = _measure(native_image_read, args.runs)
    image_rss = _measure_in_process_rss(native_image_read)
    pair_time, pair_peak = _measure(native_pair_read, args.runs)
    pair_rss = _measure_in_process_rss(native_pair_read)

    oracle_metrics = {}
    oracle_full_time = None
    if not args.skip_oracles:
        oracle_full_time, oracle_full_peak = _measure(
            oracle_full_read, args.runs
        )
        oracle_full_rss = _measure_in_process_rss(oracle_full_read)
        oracle_inspect_time, oracle_inspect_peak = _measure(
            oracle_inspect, args.runs
        )
        oracle_inspect_rss = _measure_in_process_rss(oracle_inspect)
        oracle_image_time, oracle_image_peak = _measure(
            oracle_image_read, args.runs
        )
        oracle_image_rss = _measure_in_process_rss(oracle_image_read)
        oracle_pair_time, oracle_pair_peak = _measure(
            oracle_pair_read, args.runs
        )
        oracle_pair_rss = _measure_in_process_rss(oracle_pair_read)
        oracle_metrics = {
            "oracle_write_mbps": payload_mb / oracle_write_time,
            "oracle_write_peak_mb": oracle_write_peak / 1e6,
            "oracle_write_rss_mb": oracle_write_rss / 1e6,
            "oracle_read_mbps": payload_mb / oracle_full_time,
            "oracle_read_peak_mb": oracle_full_peak / 1e6,
            "oracle_read_rss_mb": oracle_full_rss / 1e6,
            "oracle_inspect_ms": oracle_inspect_time * 1000,
            "oracle_inspect_peak_mb": oracle_inspect_peak / 1e6,
            "oracle_inspect_rss_mb": oracle_inspect_rss / 1e6,
            "oracle_image_ms": oracle_image_time * 1000,
            "oracle_image_peak_mb": oracle_image_peak / 1e6,
            "oracle_image_rss_mb": oracle_image_rss / 1e6,
            "oracle_pair_ms": oracle_pair_time * 1000,
            "oracle_pair_peak_mb": oracle_pair_peak / 1e6,
            "oracle_pair_rss_mb": oracle_pair_rss / 1e6,
        }

    decoded = native_full_read()
    assert decoded.profile == args.colmap_db_profile
    _assert_colmap_db_equal(decoded, value)
    if not args.skip_oracles:
        oracle_decoded = sceneio.read(oracle_path, format="colmap_db")
        _assert_colmap_db_equal(oracle_decoded, value)
        assert len(oracle_full_read()[1]) == value.num_images
    selected_feature = native_image_read()
    expected_feature = decoded.feature(selected_image_id)
    assert (
        selected_feature.image_id,
        selected_feature.image_name,
        selected_feature.camera_id,
    ) == (
        expected_feature.image_id,
        expected_feature.image_name,
        expected_feature.camera_id,
    )
    np.testing.assert_array_equal(
        selected_feature.keypoints, expected_feature.keypoints
    )
    np.testing.assert_array_equal(
        selected_feature.descriptors, expected_feature.descriptors
    )
    selected_graph = native_pair_read()
    expected_pair_index = value.match_graph.num_pairs // 2
    match_begin = int(value.match_graph.match_offsets[expected_pair_index])
    match_end = int(value.match_graph.match_offsets[expected_pair_index + 1])
    np.testing.assert_array_equal(
        selected_graph.matches,
        value.match_graph.matches[match_begin:match_end],
    )
    inspected = native_inspect()
    assert inspected.count == value.num_images
    assert inspected.metadata["num_matches"] == value.match_graph.num_matches

    file_mb = native_path.stat().st_size / 1e6
    result = {
        "codec": "colmap_db",
        "profile": args.colmap_db_profile,
        "payload_mb": payload_mb,
        "file_mb": file_mb,
        "write_mbps": payload_mb / native_write_time,
        "path_write_mbps": payload_mb / native_write_time,
        "read_mbps": payload_mb / native_full_time,
        "path_read_mbps": payload_mb / native_full_time,
        "mmap_peak_mb": native_full_peak / 1e6,
        "mmap_rss_mb": native_full_rss / 1e6,
        "inspect_ms": inspect_time * 1000,
        "inspect_peak_mb": inspect_peak / 1e6,
        "inspect_rss_mb": inspect_rss / 1e6,
        "partial_ms": image_time * 1000,
        "partial_peak_mb": image_peak / 1e6,
        "partial_rss_mb": image_rss / 1e6,
        "partial_image_ms": image_time * 1000,
        "partial_image_peak_mb": image_peak / 1e6,
        "partial_image_rss_mb": image_rss / 1e6,
        "partial_pair_ms": pair_time * 1000,
        "partial_pair_peak_mb": pair_peak / 1e6,
        "partial_pair_rss_mb": pair_rss / 1e6,
        "sink_write_peak_mb": native_write_peak / 1e6,
        "sink_write_rss_mb": native_write_rss / 1e6,
        **oracle_metrics,
    }
    write_row = (
        "colmap_db",
        payload_mb,
        file_mb,
        None,
        payload_mb / native_write_time,
        None,
        native_write_peak / 1e6,
        None,
        native_write_rss / 1e6,
    )
    inspect_row = (
        "colmap_db",
        native_full_time,
        inspect_time,
        native_full_peak / 1e6,
        inspect_peak / 1e6,
        native_full_rss / 1e6,
        inspect_rss / 1e6,
    )
    partial_rows = [
        (
            "colmap_db:image",
            native_full_time,
            image_time,
            native_full_peak / 1e6,
            image_peak / 1e6,
            native_full_rss / 1e6,
            image_rss / 1e6,
        ),
        (
            "colmap_db:pair",
            native_full_time,
            pair_time,
            native_full_peak / 1e6,
            pair_peak / 1e6,
            native_full_rss / 1e6,
            pair_rss / 1e6,
        ),
    ]
    display = (
        payload_mb,
        file_mb,
        payload_mb / native_write_time,
        payload_mb / native_full_time,
        (
            payload_mb / oracle_write_time
            if oracle_write_time is not None
            else None
        ),
        (
            payload_mb / oracle_full_time
            if oracle_full_time is not None
            else None
        ),
        native_full_peak / 1e6,
        native_full_rss / 1e6,
    )
    return result, write_row, inspect_row, partial_rows, display


def _benchmark_path_spec(args, tmp, spec):
    value, payload = spec.make()
    native_path = Path(tmp) / f"{spec.id}-native{spec.extension}"
    oracle_path = Path(tmp) / f"{spec.id}-oracle{spec.extension}"
    payload_bytes = spec.nbytes(value, payload)
    payload_mb = payload_bytes / 1e6

    def native_write():
        return spec.w(value, native_path)

    native_write_time, native_write_peak = _measure(
        native_write,
        args.runs,
    )
    native_write_rss = _measure_in_process_rss(native_write)

    def native_read():
        if args.cold_cache:
            _evict_file_cache(native_path)
        return spec.r(native_path)

    native_read_time, native_read_peak = _measure(
        native_read,
        args.runs,
    )
    native_read_rss = _measure_in_process_rss(native_read)

    def native_inspect():
        if args.cold_cache:
            _evict_file_cache(native_path)
        return sceneio.inspect(native_path, format=spec.id)

    inspect_time, inspect_peak = _measure(native_inspect, args.runs)
    inspect_rss = _measure_in_process_rss(native_inspect)

    partial_time = partial_peak = partial_rss = None
    if spec.partial is not None:
        def native_partial():
            if args.cold_cache:
                _evict_file_cache(native_path)
            return spec.partial(native_path)

        partial_time, partial_peak = _measure(native_partial, args.runs)
        partial_rss = _measure_in_process_rss(native_partial)
        spec.assert_partial(native_partial(), payload)

    oracle_write_time = oracle_read_time = None
    oracle_inspect_time = oracle_partial_time = None
    oracle_write_peak = oracle_write_rss = None
    oracle_read_peak = oracle_read_rss = None
    oracle_inspect_peak = oracle_inspect_rss = None
    oracle_partial_peak = oracle_partial_rss = None
    if (
        not args.skip_oracles
        and spec.ow is not None
        and spec.orr is not None
    ):
        def oracle_write():
            return spec.ow(payload, oracle_path)

        oracle_write_time, oracle_write_peak = _measure(
            oracle_write,
            args.runs,
        )
        oracle_write_rss = _measure_in_process_rss(oracle_write)

        def oracle_read():
            if args.cold_cache:
                _evict_file_cache(native_path)
            return spec.orr(native_path)

        oracle_read_time, oracle_read_peak = _measure(
            oracle_read,
            args.runs,
        )
        oracle_read_rss = _measure_in_process_rss(oracle_read)
        spec.assert_oracle(oracle_read(), payload)
        spec.assert_native(spec.r(oracle_path), payload)
        if spec.oracle_inspect is not None:
            def oracle_inspect():
                if args.cold_cache:
                    _evict_file_cache(native_path)
                return spec.oracle_inspect(native_path)

            oracle_inspect_time, oracle_inspect_peak = _measure(
                oracle_inspect,
                args.runs,
            )
            oracle_inspect_rss = _measure_in_process_rss(oracle_inspect)
            spec.assert_oracle_inspect(native_inspect(), oracle_inspect())
        if spec.oracle_partial is not None:
            def oracle_partial():
                if args.cold_cache:
                    _evict_file_cache(native_path)
                return spec.oracle_partial(native_path)

            oracle_partial_time, oracle_partial_peak = _measure(
                oracle_partial,
                args.runs,
            )
            oracle_partial_rss = _measure_in_process_rss(oracle_partial)
            spec.assert_oracle_partial(oracle_partial(), payload)

    spec.assert_native(native_read(), payload)
    inspected = native_inspect()
    native_size = _stored_size(native_path)
    if inspected.byte_size != native_size:
        raise AssertionError(f"{spec.id} inspection byte size differs from file")

    file_mb = native_size / 1e6
    oracle_metrics = {}
    if oracle_write_time is not None and oracle_read_time is not None:
        oracle_metrics = {
            "oracle_inspect_ms": (
                oracle_inspect_time * 1000
                if oracle_inspect_time is not None
                else None
            ),
            "oracle_inspect_peak_mb": (
                oracle_inspect_peak / 1e6
                if oracle_inspect_peak is not None
                else None
            ),
            "oracle_inspect_rss_mb": (
                oracle_inspect_rss / 1e6
                if oracle_inspect_rss is not None
                else None
            ),
            "oracle_partial_ms": (
                oracle_partial_time * 1000
                if oracle_partial_time is not None
                else None
            ),
            "oracle_partial_peak_mb": (
                oracle_partial_peak / 1e6
                if oracle_partial_peak is not None
                else None
            ),
            "oracle_partial_rss_mb": (
                oracle_partial_rss / 1e6
                if oracle_partial_rss is not None
                else None
            ),
            "oracle_write_mbps": payload_mb / oracle_write_time,
            "oracle_write_peak_mb": oracle_write_peak / 1e6,
            "oracle_write_rss_mb": oracle_write_rss / 1e6,
            "oracle_read_mbps": payload_mb / oracle_read_time,
            "oracle_read_peak_mb": oracle_read_peak / 1e6,
            "oracle_read_rss_mb": oracle_read_rss / 1e6,
        }
    result = {
        "codec": spec.id,
        "payload_mb": payload_mb,
        "file_mb": file_mb,
        "write_mbps": payload_mb / native_write_time,
        "path_write_mbps": payload_mb / native_write_time,
        "read_mbps": payload_mb / native_read_time,
        "path_read_mbps": payload_mb / native_read_time,
        "mmap_peak_mb": native_read_peak / 1e6,
        "mmap_rss_mb": native_read_rss / 1e6,
        "inspect_ms": inspect_time * 1000,
        "inspect_peak_mb": inspect_peak / 1e6,
        "inspect_rss_mb": inspect_rss / 1e6,
        "sink_write_peak_mb": native_write_peak / 1e6,
        "sink_write_rss_mb": native_write_rss / 1e6,
        **oracle_metrics,
    }
    partial_row = None
    if partial_time is not None:
        result.update(
            partial_ms=partial_time * 1000,
            partial_peak_mb=partial_peak / 1e6,
            partial_rss_mb=partial_rss / 1e6,
        )
        partial_row = (
            spec.id,
            native_read_time,
            partial_time,
            native_read_peak / 1e6,
            partial_peak / 1e6,
            native_read_rss / 1e6,
            partial_rss / 1e6,
        )
    write_row = (
        spec.id,
        payload_mb,
        file_mb,
        None,
        payload_mb / native_write_time,
        None,
        native_write_peak / 1e6,
        None,
        native_write_rss / 1e6,
    )
    inspect_row = (
        spec.id,
        native_read_time,
        inspect_time,
        native_read_peak / 1e6,
        inspect_peak / 1e6,
        native_read_rss / 1e6,
        inspect_rss / 1e6,
    )
    display = (
        payload_mb,
        file_mb,
        payload_mb / native_write_time,
        payload_mb / native_read_time,
        (
            payload_mb / oracle_write_time
            if oracle_write_time is not None
            else None
        ),
        (
            payload_mb / oracle_read_time
            if oracle_read_time is not None
            else None
        ),
        native_read_peak / 1e6,
        native_read_rss / 1e6,
    )
    return result, write_row, inspect_row, partial_row, display


def _benchmark_gltf(args, tmp):
    points = max(3, int(300_000 * args.scale))
    record, payload = _mesh_scene(points)
    payload_bytes = sum(value.nbytes for value in payload.values())
    payload_mb = payload_bytes / 1e6
    path = Path(tmp) / "gltf_scene.gltf"
    peer = path.with_suffix(".bin")
    buffer_uri = peer.name

    def _encode():
        return _core.write_gltf(record, buffer_uri)

    json_bytes, binary_bytes = _encode()
    json_bytes = bytes(json_bytes)
    binary_bytes = bytes(binary_bytes)
    file_mb = (len(json_bytes) + len(binary_bytes)) / 1e6

    core_write_time, bytes_write_peak = _measure(
        _encode, args.runs
    )
    bytes_write_rss = _measure_in_process_rss(_encode)

    def _buffer_write():
        document, binary = _encode()
        path.write_bytes(document)
        peer.write_bytes(binary)

    def _sink_write():
        return sceneio.write(record, path, format="gltf")

    bytes_path_write_time, _ = _measure(
        _buffer_write, args.runs
    )
    sink_write_time, sink_write_peak = _measure(
        _sink_write, args.runs
    )
    sink_write_rss = _measure_in_process_rss(_sink_write)
    if (
        path.read_bytes() != json_bytes
        or peer.read_bytes() != binary_bytes
    ):
        raise AssertionError(
            "glTF file sink output differs from buffer encoder")

    def _core_read():
        return _core.read_gltf(
            json_bytes, {buffer_uri: binary_bytes})

    core_read_time, _ = _measure(_core_read, args.runs)

    def _bytes_read():
        return _core.read_gltf(
            path.read_bytes(), {buffer_uri: peer.read_bytes()})

    def _path_read():
        if args.cold_cache:
            _evict_file_cache(path)
            _evict_file_cache(peer)
        return sceneio.read(path, format="gltf")

    _, bytes_peak = _measure(_bytes_read, args.runs)
    path_read_time, mmap_peak = _measure(
        _path_read, args.runs
    )
    bytes_rss = _measure_in_process_rss(_bytes_read)
    mmap_rss = _measure_in_process_rss(_path_read)

    def _inspect():
        if args.cold_cache:
            _evict_file_cache(path)
        return sceneio.inspect(path, format="gltf")

    inspect_time, inspect_peak = _measure(
        _inspect, args.runs
    )
    inspect_rss = _measure_in_process_rss(_inspect)

    def _partial():
        if args.cold_cache:
            _evict_file_cache(path)
            _evict_file_cache(peer)
        return sceneio.read_partial(
            path, format="gltf", primitive_id=0)

    partial_time, partial_peak = _measure(
        _partial, args.runs
    )
    partial_rss = _measure_in_process_rss(_partial)

    oracle_write_time = None
    oracle_read_time = None
    if trimesh is not None and not args.skip_oracles:
        if getattr(args, "strict_oracles", False):
            oracle_files = _trimesh_gltf_w(payload)
            oracle_write_time = _measure(
                lambda: _trimesh_gltf_w(payload),
                args.runs,
            )[0]
            oracle_read_time = _measure(
                lambda: _trimesh_gltf_r(oracle_files),
                args.runs,
            )[0]
        else:
            oracle_files = _try(
                lambda: _trimesh_gltf_w(payload))
            if oracle_files is not None:
                measured = _try(
                    lambda: _measure(
                        lambda: _trimesh_gltf_w(payload),
                        args.runs,
                    ))
                oracle_write_time = measured[0] if measured else None
                measured = _try(
                    lambda: _measure(
                        lambda: _trimesh_gltf_r(oracle_files),
                        args.runs,
                    ))
                oracle_read_time = measured[0] if measured else None

    result = {
        "codec": "gltf",
        "payload_mb": payload_mb,
        "file_mb": file_mb,
        "write_mbps": payload_mb / core_write_time,
        "bytes_path_write_mbps": (
            payload_mb / bytes_path_write_time),
        "path_write_mbps": payload_mb / sink_write_time,
        "read_mbps": payload_mb / core_read_time,
        "path_read_mbps": payload_mb / path_read_time,
        "oracle_write_mbps": (
            payload_mb / oracle_write_time
            if oracle_write_time is not None else None),
        "oracle_read_mbps": (
            payload_mb / oracle_read_time
            if oracle_read_time is not None else None),
        "bytes_peak_mb": bytes_peak / 1e6,
        "mmap_peak_mb": mmap_peak / 1e6,
        "bytes_rss_mb": bytes_rss / 1e6,
        "mmap_rss_mb": mmap_rss / 1e6,
        "inspect_ms": inspect_time * 1000,
        "inspect_peak_mb": inspect_peak / 1e6,
        "inspect_rss_mb": inspect_rss / 1e6,
        "partial_ms": partial_time * 1000,
        "partial_peak_mb": partial_peak / 1e6,
        "partial_rss_mb": partial_rss / 1e6,
        "bytes_write_peak_mb": bytes_write_peak / 1e6,
        "sink_write_peak_mb": sink_write_peak / 1e6,
        "bytes_write_rss_mb": bytes_write_rss / 1e6,
        "sink_write_rss_mb": sink_write_rss / 1e6,
    }
    write_row = (
        "gltf",
        payload_mb,
        file_mb,
        payload_mb / bytes_path_write_time,
        payload_mb / sink_write_time,
        bytes_write_peak / 1e6,
        sink_write_peak / 1e6,
        bytes_write_rss / 1e6,
        sink_write_rss / 1e6,
    )
    inspect_row = (
        "gltf",
        path_read_time,
        inspect_time,
        mmap_peak / 1e6,
        inspect_peak / 1e6,
        mmap_rss / 1e6,
        inspect_rss / 1e6,
    )
    partial_row = (
        "gltf",
        path_read_time,
        partial_time,
        mmap_peak / 1e6,
        partial_peak / 1e6,
        mmap_rss / 1e6,
        partial_rss / 1e6,
    )
    display = (
        payload_mb,
        file_mb,
        payload_mb / core_write_time,
        payload_mb / core_read_time,
        payload_mb / path_read_time,
        result["oracle_write_mbps"],
        result["oracle_read_mbps"],
        bytes_peak / 1e6,
        mmap_peak / 1e6,
        bytes_rss / 1e6,
        mmap_rss / 1e6,
    )
    return result, write_row, inspect_row, partial_row, display


def _run_benchmark(args, tmp):
    from bench.io_bench import qualification

    pose_bundle = _poses_and_reconstruction(args.scale)
    reconstruction = pose_bundle[0]
    specs = _specs(args.scale, pose_bundle)
    path_specs = [
        *build_container_specs(args.scale),
        *build_media_path_specs(args.scale),
    ]
    directory_specs = _directory_specs(
        reconstruction, args.scale, tmp
    )
    include_colmap_db = True
    include_gltf = True
    qualification.validate_benchmark_coverage(
        [
            *(spec.id for spec in specs),
            "gltf",
            "colmap_db",
            *(spec.id for spec in directory_specs),
            *(spec.id for spec in path_specs),
        ]
    )
    if getattr(args, "strict_oracles", False):
        qualification.validate_strict_providers(
            specs,
            special_available={
                "gltf": trimesh is not None,
                "colmap_db": True,
            },
            path_specs=path_specs,
        )
    if args.only:
        requested = set(args.only)
        known = {spec.id for spec in specs} | {
            spec.id for spec in directory_specs
        } | {spec.id for spec in path_specs} | {"colmap_db", "gltf"}
        unknown = requested - known
        if unknown:
            raise ValueError(
                "unknown --only format: " + ", ".join(sorted(unknown))
            )
        specs = [spec for spec in specs if spec.id in requested]
        directory_specs = [
            spec for spec in directory_specs if spec.id in requested
        ]
        path_specs = [
            spec for spec in path_specs if spec.id in requested
        ]
        include_colmap_db = "colmap_db" in requested
        include_gltf = "gltf" in requested
    failures = []
    results = []
    write_rows = []
    o4_rows = []
    inspect_rows = []
    partial_rows = []

    print_primary_header()
    for s in specs:
        try:
            rec, payload = s.make()
            enc = bytes(s.w(rec))
            if not args.skip_oracles and s.id in {
                "colmap_fused_visibility",
                "colmap_mvs_consistency",
                "colmap_mvs_depth",
                "colmap_mvs_normal",
            }:
                qualification.validate_dense_oracle_parity(
                    s, rec, payload, enc
                )
            pbytes = s.nbytes(rec, payload)
            pmb = pbytes / 1e6
            fmb = len(enc) / 1e6

            wt, _ = _measure(lambda: s.w(rec), args.runs)
            rt, _ = _measure(lambda: s.r(enc), args.runs)
            sioW, sioR = pmb / wt, pmb / rt
            o4_metrics = {}
            typed_adapter_metrics = None
            ply_variant_metrics = None
            pcd_variant_metrics = None
            spz_profile_metrics = None

            if s.id == "ply":
                ply_variant_metrics = {
                    "binary_little_endian": {
                        "file_mb": fmb,
                        "write_mbps": sioW,
                        "read_mbps": sioR,
                    }
                }
                reference_fields = {
                    name: np.asarray(getattr(rec, name))
                    for name in ("positions", "colors", "normals")
                }
                for encoding in ("ascii", "binary_big_endian"):
                    writer = partial(_core.write_ply, rec, encoding)
                    variant_write_time, _ = _measure(writer, args.runs)
                    variant = bytes(writer())
                    reader = partial(_core.read_ply, variant)
                    variant_read_time, _ = _measure(reader, args.runs)
                    decoded = reader()
                    if not all(
                        np.array_equal(
                            np.asarray(getattr(decoded, name)), expected
                        )
                        for name, expected in reference_fields.items()
                    ):
                        raise AssertionError(
                            f"PLY {encoding} variant changed decoded values"
                        )
                    ply_variant_metrics[encoding] = {
                        "file_mb": len(variant) / 1e6,
                        "write_mbps": pmb / variant_write_time,
                        "read_mbps": pmb / variant_read_time,
                    }

            if s.id == "pcd":
                pcd_variant_metrics = {
                    "binary": {
                        "file_mb": fmb,
                        "write_mbps": sioW,
                        "read_mbps": sioR,
                    }
                }
                reference_fields = {
                    name: np.asarray(getattr(rec, name))
                    for name in ("positions", "colors", "normals")
                }
                for encoding in ("ascii", "binary_compressed"):
                    writer = partial(_core.write_pcd, rec, encoding)
                    variant_write_time, _ = _measure(writer, args.runs)
                    variant = bytes(writer())
                    reader = partial(_core.read_pcd, variant)
                    variant_read_time, _ = _measure(reader, args.runs)
                    decoded = reader()
                    if not all(
                        np.array_equal(
                            np.asarray(getattr(decoded, name)), expected
                        )
                        for name, expected in reference_fields.items()
                    ):
                        raise AssertionError(
                            f"PCD {encoding} variant changed decoded values"
                        )
                    pcd_variant_metrics[encoding] = {
                        "file_mb": len(variant) / 1e6,
                        "write_mbps": pmb / variant_write_time,
                        "read_mbps": pmb / variant_read_time,
                    }

            if s.id == "spz":
                legacy_settings = splat_family.SPZ_PROFILE_SETTINGS[
                    "legacy_v3_gzip"
                ]
                if (
                    enc[:2].hex() != legacy_settings["container_magic"]
                ):
                    raise AssertionError(
                        "SPZ legacy profile did not produce a v3 gzip container"
                    )
                v4_settings = splat_family.SPZ_PROFILE_SETTINGS[
                    "ngsp_v4_zstd"
                ]
                v4_writer = partial(
                    splat_family.write_spz_profile,
                    rec,
                    "ngsp_v4_zstd",
                )
                v4_write_time, _ = _measure(v4_writer, args.runs)
                v4_blob = bytes(v4_writer())
                if (
                    v4_blob[:4].hex() != v4_settings["container_magic"]
                    or v4_blob[4:8] != b"\x04\x00\x00\x00"
                ):
                    raise AssertionError(
                        "SPZ NGSP profile did not produce a v4 zstd container"
                    )
                v4_reader = partial(_core.read_spz, v4_blob)
                v4_read_time, _ = _measure(v4_reader, args.runs)
                legacy_decoded = s.r(enc)
                v4_decoded = v4_reader()
                if not all(
                    np.array_equal(
                        np.asarray(getattr(legacy_decoded, field)),
                        np.asarray(getattr(v4_decoded, field)),
                    )
                    for field in (
                        "means",
                        "scales",
                        "quaternions",
                        "opacities",
                        "sh_dc",
                        "sh_rest",
                    )
                ):
                    raise AssertionError(
                        "SPZ v3 and v4 profiles changed decoded values"
                    )
                spz_profile_metrics = {
                    "legacy_v3_gzip": {
                        **dict(legacy_settings),
                        "file_mb": fmb,
                        "write_mbps": sioW,
                        "read_mbps": sioR,
                    },
                    "ngsp_v4_zstd": {
                        **dict(v4_settings),
                        "file_mb": len(v4_blob) / 1e6,
                        "write_mbps": pmb / v4_write_time,
                        "read_mbps": pmb / v4_read_time,
                    },
                }

            # O4 controls retain a deterministic one-lane/worker-off reference
            # beside the optimized defaults. WebP separately measures the old
            # forced effort=100 setting and a palette input on which libwebp
            # actually schedules its lossless side worker.
            if s.id == "webp":
                old_webp = partial(
                    _core.write_webp, rec, True, 90.0, False, 100, 4
                )
                old_time, _ = _measure(old_webp, args.runs)
                original = np.asarray(rec.pixels)
                if not np.array_equal(
                    np.asarray(_core.read_webp(old_webp()).pixels), original
                ):
                    raise AssertionError("lower WebP effort changed decoded pixels")

                palette_rec, palette_values = _img_webp_palette(
                    max(32, int(1024 * args.scale**0.5)),
                    max(32, int(1024 * args.scale**0.5)),
                )
                worker_off = partial(
                    _core.write_webp,
                    palette_rec,
                    True,
                    90.0,
                    False,
                )
                worker_on = partial(_core.write_webp, palette_rec)
                worker_off_time, _ = _measure(worker_off, args.runs)
                launch_count = _core._webp_worker_launch_count()
                worker_on_time, _ = _measure(worker_on, args.runs)
                if _core._webp_worker_launch_count() <= launch_count:
                    raise AssertionError("WebP side-worker path was not reached")
                worker_off_bytes = bytes(worker_off())
                worker_on_bytes = bytes(worker_on())
                if worker_off_bytes != worker_on_bytes:
                    raise AssertionError("WebP worker output differs")
                if not np.array_equal(
                    np.asarray(_core.read_webp(worker_on_bytes).pixels),
                    palette_values,
                ):
                    raise AssertionError("WebP worker decode differs")
                palette_mb = palette_values.nbytes / 1e6
                o4_rows.extend(
                    [
                        (
                            "webp",
                            "balanced-config",
                            pmb / old_time,
                            sioW,
                            "pixels",
                        ),
                        (
                            "webp",
                            "workers-palette",
                            palette_mb / worker_off_time,
                            palette_mb / worker_on_time,
                            "bytes",
                        ),
                    ]
                )
                o4_metrics.update(
                    {
                        "write_old_mbps": pmb / old_time,
                        "write_worker_off_mbps": palette_mb
                        / worker_off_time,
                        "write_optimized_mbps": sioW,
                        "write_worker_on_mbps": palette_mb / worker_on_time,
                    }
                )
            elif s.id == "webm":
                worker_off = partial(
                    _core.write_webm,
                    rec,
                    90.0,
                    False,
                    4,
                )
                worker_off_time, _ = _measure(worker_off, args.runs)
                if bytes(worker_off()) != enc:
                    raise AssertionError("WebM worker output differs")
                o4_rows.append(
                    (
                        "webm",
                        "workers-write",
                        pmb / worker_off_time,
                        sioW,
                        "bytes",
                    )
                )
                o4_metrics.update(
                    {
                        "write_worker_off_mbps": pmb / worker_off_time,
                        "write_worker_on_mbps": sioW,
                    }
                )
                for temporal_codec in ("vp8", "vp9"):
                    one_lane = partial(
                        _core.write_webm_temporal,
                        rec,
                        temporal_codec,
                        82.0,
                        1,
                        6,
                        120,
                    )
                    worker_lanes = partial(
                        _core.write_webm_temporal,
                        rec,
                        temporal_codec,
                        82.0,
                        0,
                        6,
                        120,
                    )
                    one_lane_time, _ = _measure(one_lane, args.runs)
                    worker_time, _ = _measure(worker_lanes, args.runs)
                    temporal_bytes = bytes(worker_lanes())
                    decode_time, _ = _measure(
                        partial(_core.read_webm, temporal_bytes), args.runs
                    )
                    temporal_decoded = _core.read_webm(temporal_bytes)
                    if (
                        temporal_decoded.timestamps_ns.tolist()
                        != rec.timestamps_ns.tolist()
                        or temporal_decoded.durations_ns.tolist()
                        != rec.durations_ns.tolist()
                    ):
                        raise AssertionError(
                            f"WebM {temporal_codec} temporal timing differs"
                        )
                    o4_rows.append(
                        (
                            "webm",
                            f"{temporal_codec}-temporal-workers",
                            pmb / one_lane_time,
                            pmb / worker_time,
                            "timeline",
                        )
                    )
                    o4_metrics.update(
                        {
                            f"{temporal_codec}_temporal_write_1_mbps": (
                                pmb / one_lane_time
                            ),
                            f"{temporal_codec}_temporal_write_auto_mbps": (
                                pmb / worker_time
                            ),
                            f"{temporal_codec}_temporal_read_mbps": (
                                pmb / decode_time
                            ),
                            f"{temporal_codec}_temporal_encoded_bytes": len(
                                temporal_bytes
                            ),
                        }
                    )
            elif s.id in {"xyz", "exr", "las"}:
                if s.id == "xyz":
                    one_lane_write = partial(
                        _core.write_xyz, rec, _lanes=1
                    )
                    label = "format"
                elif s.id == "exr":
                    one_lane_write = partial(
                        _core.write_exr, rec, _lanes=1
                    )
                    label = "planar"
                else:
                    one_lane_write = partial(
                        _core.write_las, rec, _lanes=1
                    )
                    label = "points"
                one_write_time, _ = _measure(one_lane_write, args.runs)
                if bytes(one_lane_write()) != enc:
                    raise AssertionError(f"{s.id} lane output differs")
                o4_rows.append(
                    (s.id, f"{label}-write", pmb / one_write_time, sioW, "bytes")
                )
                o4_metrics.update(
                    {
                        "write_one_lane_mbps": pmb / one_write_time,
                        "write_optimized_mbps": sioW,
                    }
                )
                if s.id in {"exr", "las"}:
                    if s.id == "exr":
                        one_lane_read = partial(
                            _core.read_exr, enc, _lanes=1
                        )
                    else:
                        one_lane_read = partial(
                            _core.read_las, enc, _lanes=1
                        )
                    one_read_time, _ = _measure(one_lane_read, args.runs)
                    one_decoded = one_lane_read()
                    optimized_decoded = s.r(enc)
                    if s.id == "exr":
                        same_values = np.array_equal(
                            np.asarray(one_decoded.pixels),
                            np.asarray(optimized_decoded.pixels),
                        )
                        same_metadata = (
                            one_decoded.height,
                            one_decoded.width,
                            one_decoded.channels,
                            one_decoded.dtype,
                            one_decoded.color_space,
                            one_decoded.alpha_mode,
                            one_decoded.maxval,
                        ) == (
                            optimized_decoded.height,
                            optimized_decoded.width,
                            optimized_decoded.channels,
                            optimized_decoded.dtype,
                            optimized_decoded.color_space,
                            optimized_decoded.alpha_mode,
                            optimized_decoded.maxval,
                        )
                    else:
                        same_values = all(
                            np.array_equal(
                                np.asarray(getattr(one_decoded, field)),
                                np.asarray(getattr(optimized_decoded, field)),
                            )
                            for field in (
                                "positions",
                                "colors16",
                                "intensities",
                            )
                        ) and np.array_equal(
                            one_decoded.origin, optimized_decoded.origin
                        )
                        same_metadata = (
                            one_decoded.num_points,
                            one_decoded.coordinate_frame,
                            one_decoded.scale_to_meters,
                            one_decoded.intensity_range,
                        ) == (
                            optimized_decoded.num_points,
                            optimized_decoded.coordinate_frame,
                            optimized_decoded.scale_to_meters,
                            optimized_decoded.intensity_range,
                        )
                    if not same_values or not same_metadata:
                        raise AssertionError(
                            f"{s.id} lane decode differs"
                        )
                    o4_rows.append(
                        (
                            s.id,
                            f"{label}-read",
                            pmb / one_read_time,
                            sioR,
                            "values",
                        )
                    )
                    o4_metrics.update(
                        {
                            "read_one_lane_mbps": pmb / one_read_time,
                            "read_optimized_mbps": sioR,
                        }
                    )

            if s.id == "png":
                u16_side = max(1, int(1024 * args.scale**0.5))
                u16 = (
                    (
                        np.arange(u16_side * u16_side * 3, dtype=np.uint32)
                        * 40503
                    )
                    & 0xFFFF
                ).astype(np.uint16).reshape(u16_side, u16_side, 3)
                u16_image = _core.image(u16, color_space="srgb")
                png16_one_write = partial(
                    _core.write_png, u16_image, _lanes=1
                )
                png16_fast_write = partial(_core.write_png, u16_image)
                png16_one_time, _ = _measure(png16_one_write, args.runs)
                png16_fast_time, _ = _measure(png16_fast_write, args.runs)
                png16_data = bytes(png16_fast_write())
                if bytes(png16_one_write()) != png16_data:
                    raise AssertionError("PNG16 lane output differs")
                png16_one_read = partial(
                    _core.read_png, png16_data, _lanes=1
                )
                png16_fast_read = partial(_core.read_png, png16_data)
                png16_one_read_time, _ = _measure(png16_one_read, args.runs)
                png16_fast_read_time, _ = _measure(
                    png16_fast_read, args.runs
                )
                png16_one_values = np.asarray(png16_one_read().pixels)
                png16_fast_values = np.asarray(png16_fast_read().pixels)
                if not (
                    np.array_equal(png16_one_values, png16_fast_values)
                    and np.array_equal(png16_fast_values, u16)
                ):
                    raise AssertionError("PNG16 lane decode differs")
                png16_mb = u16.nbytes / 1e6
                o4_rows.extend(
                    [
                        (
                            "png16",
                            "swap-write",
                            png16_mb / png16_one_time,
                            png16_mb / png16_fast_time,
                            "bytes",
                        ),
                        (
                            "png16",
                            "swap-read",
                            png16_mb / png16_one_read_time,
                            png16_mb / png16_fast_read_time,
                            "values",
                        ),
                    ]
                )
                o4_metrics.update(
                    {
                        "png16_write_one_lane_mbps": png16_mb
                        / png16_one_time,
                        "png16_write_optimized_mbps": png16_mb
                        / png16_fast_time,
                        "png16_read_one_lane_mbps": png16_mb
                        / png16_one_read_time,
                        "png16_read_optimized_mbps": png16_mb
                        / png16_fast_read_time,
                    }
                )

            # Compare the legacy bytes+Path.write_bytes route with the public O3
            # file sink, then compare whole-file bytes + copy decode with the
            # public mmap path. NPY/FLO also expose the O2 mapped output view.
            fp = os.path.join(tmp, f"{s.id}.bin")

            def _bytes_write(fp=fp, w=s.w, value=rec):
                return Path(fp).write_bytes(w(value))

            def _sink_write(fp=fp, codec_id=s.id, value=rec):
                return sceneio.write(value, fp, format=codec_id)

            bytes_write_time, bytes_write_peak = _measure(
                _bytes_write, args.runs
            )
            bytes_write_rss = _measure_in_process_rss(_bytes_write)
            sink_time, sink_write_peak = _measure(_sink_write, args.runs)
            sink_write_rss = _measure_in_process_rss(_sink_write)
            with open(fp, "rb") as fh:
                if fh.read() != enc:
                    raise AssertionError("file sink output differs from buffer encoder")
            path_write = pmb / sink_time
            bytes_path_write = pmb / bytes_write_time
            write_rows.append(
                (
                    s.id,
                    pmb,
                    fmb,
                    bytes_path_write,
                    path_write,
                    bytes_write_peak / 1e6,
                    sink_write_peak / 1e6,
                    bytes_write_rss / 1e6,
                    sink_write_rss / 1e6,
                )
            )

            def _bytes_read(fp=fp, r=s.r):
                with open(fp, "rb") as fh:
                    return r(fh.read())

            def _mmap_read(fp=fp, codec_id=s.id):
                if args.cold_cache:
                    _evict_file_cache(fp)
                return sceneio.read(fp, format=codec_id)

            _, bytes_peak = _measure(_bytes_read, args.runs)
            path_time, mmap_peak = _measure(_mmap_read, args.runs)
            bytes_rss = _measure_in_process_rss(_bytes_read)
            mmap_rss = _measure_in_process_rss(_mmap_read)
            path_read = pmb / path_time

            def _inspect(fp=fp, codec_id=s.id):
                if args.cold_cache:
                    _evict_file_cache(fp)
                return sceneio.inspect(fp, format=codec_id)

            inspect_time, inspect_peak = _measure(_inspect, args.runs)
            inspect_rss = _measure_in_process_rss(_inspect)
            inspect_rows.append(
                (
                    s.id,
                    path_time,
                    inspect_time,
                    mmap_peak / 1e6,
                    inspect_peak / 1e6,
                    mmap_rss / 1e6,
                    inspect_rss / 1e6,
                )
            )
            if s.id == "flo":
                typed_record = _core.flow_field(rec)
                typed_path = os.path.join(tmp, "flo-typed.bin")

                def _typed_read(fp=fp):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.read_flow(fp, format="flo")

                def _typed_write(
                    destination=typed_path,
                    value=typed_record,
                ):
                    return sceneio.write_flow(
                        value, destination, format="flo"
                    )

                def _typed_inspect(fp=fp):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.inspect_flow(fp, format="flo")

                typed_read_time, typed_read_peak = _measure(
                    _typed_read, args.runs
                )
                typed_read_rss = _measure_in_process_rss(_typed_read)
                typed_write_time, typed_write_peak = _measure(
                    _typed_write, args.runs
                )
                typed_write_rss = _measure_in_process_rss(_typed_write)
                typed_inspect_time, typed_inspect_peak = _measure(
                    _typed_inspect, args.runs
                )
                typed_inspect_rss = _measure_in_process_rss(_typed_inspect)
                typed_decoded = _typed_read()
                if not np.array_equal(
                    np.asarray(typed_decoded.vectors), rec, equal_nan=True
                ):
                    raise AssertionError("typed FLO values differ")
                if Path(typed_path).read_bytes() != enc:
                    raise AssertionError("typed FLO sink bytes differ")
                typed_info = _typed_inspect()
                if (
                    typed_info.shape != rec.shape
                    or typed_info.metadata.get("component_order") != "uv"
                ):
                    raise AssertionError("typed FLO inspection differs")
                typed_adapter_metrics = {
                    "format": "flo",
                    "read_mbps": pmb / typed_read_time,
                    "read_peak_mb": typed_read_peak / 1e6,
                    "read_rss_mb": typed_read_rss / 1e6,
                    "write_mbps": pmb / typed_write_time,
                    "write_peak_mb": typed_write_peak / 1e6,
                    "write_rss_mb": typed_write_rss / 1e6,
                    "inspect_ms": typed_inspect_time * 1000,
                    "inspect_peak_mb": typed_inspect_peak / 1e6,
                    "inspect_rss_mb": typed_inspect_rss / 1e6,
                }
            elif s.id == "pfm":
                depth_encoding = sceneio.DepthEncoding(
                    "meters", 1.0, "none"
                )
                typed_record = _core.depth_map(rec)
                typed_path = os.path.join(tmp, "pfm-typed.bin")
                height, width = rec.shape
                typed_window = (
                    height // 4,
                    max(height // 4 + 1, 3 * height // 4),
                    width // 4,
                    max(width // 4 + 1, 3 * width // 4),
                )

                def _typed_read(fp=fp):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.read_depth(
                        fp,
                        format="pfm",
                        encoding=depth_encoding,
                    )

                def _typed_write(
                    destination=typed_path,
                    value=typed_record,
                ):
                    return sceneio.write_depth(
                        value,
                        destination,
                        format="pfm",
                        encoding=depth_encoding,
                    )

                def _typed_inspect(fp=fp):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.inspect_depth(
                        fp,
                        format="pfm",
                        encoding=depth_encoding,
                    )

                def _typed_partial(fp=fp):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.read_depth(
                        fp,
                        format="pfm",
                        encoding=depth_encoding,
                        window=typed_window,
                    )

                typed_read_time, typed_read_peak = _measure(
                    _typed_read, args.runs
                )
                typed_read_rss = _measure_in_process_rss(_typed_read)
                typed_write_time, typed_write_peak = _measure(
                    _typed_write, args.runs
                )
                typed_write_rss = _measure_in_process_rss(_typed_write)
                typed_inspect_time, typed_inspect_peak = _measure(
                    _typed_inspect, args.runs
                )
                typed_inspect_rss = _measure_in_process_rss(_typed_inspect)
                typed_partial_time, typed_partial_peak = _measure(
                    _typed_partial, args.runs
                )
                typed_partial_rss = _measure_in_process_rss(_typed_partial)
                typed_decoded = _typed_read()
                if not np.array_equal(
                    np.asarray(typed_decoded.depth), rec, equal_nan=True
                ):
                    raise AssertionError("typed PFM values differ")
                if Path(typed_path).read_bytes() != enc:
                    raise AssertionError("typed PFM sink bytes differ")
                typed_info = _typed_inspect()
                if (
                    typed_info.shape != rec.shape
                    or typed_info.metadata.get("scale_to_meters") != 1.0
                ):
                    raise AssertionError("typed PFM inspection differs")
                row_start, row_stop, col_start, col_stop = typed_window
                if not np.array_equal(
                    np.asarray(_typed_partial().depth),
                    rec[row_start:row_stop, col_start:col_stop],
                    equal_nan=True,
                ):
                    raise AssertionError("typed PFM window differs")
                typed_adapter_metrics = {
                    "format": "pfm",
                    "read_mbps": pmb / typed_read_time,
                    "read_peak_mb": typed_read_peak / 1e6,
                    "read_rss_mb": typed_read_rss / 1e6,
                    "write_mbps": pmb / typed_write_time,
                    "write_peak_mb": typed_write_peak / 1e6,
                    "write_rss_mb": typed_write_rss / 1e6,
                    "inspect_ms": typed_inspect_time * 1000,
                    "inspect_peak_mb": typed_inspect_peak / 1e6,
                    "inspect_rss_mb": typed_inspect_rss / 1e6,
                    "partial_ms": typed_partial_time * 1000,
                    "partial_peak_mb": typed_partial_peak / 1e6,
                    "partial_rss_mb": typed_partial_rss / 1e6,
                }
            elif s.id == "exr":
                typed_side = max(1, int(1024 * args.scale**0.5))
                depth_values = np.random.default_rng(20260724).standard_normal(
                    (typed_side, typed_side),
                    dtype=np.float32,
                )
                depth_encoding = sceneio.DepthEncoding(
                    "meters", 1.0, "nonfinite", "Z"
                )
                typed_record = _core.depth_map(
                    depth_values,
                    invalid_policy="nonfinite",
                )
                typed_source = os.path.join(tmp, "exr-depth-source.bin")
                typed_path = os.path.join(tmp, "exr-depth-output.bin")
                typed_bytes = bytes(
                    _core.write_exr_depth(
                        typed_record,
                        depth_encoding.unit,
                        depth_encoding.scale_to_meters,
                        depth_encoding.invalid_policy,
                        depth_encoding.channel_name,
                    )
                )
                Path(typed_source).write_bytes(typed_bytes)
                typed_mb = depth_values.nbytes / 1e6

                def _typed_read(fp=typed_source):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.read_depth(
                        fp,
                        format="exr",
                        encoding=depth_encoding,
                    )

                def _typed_write(
                    destination=typed_path,
                    value=typed_record,
                ):
                    return sceneio.write_depth(
                        value,
                        destination,
                        format="exr",
                        encoding=depth_encoding,
                    )

                def _typed_inspect(fp=typed_source):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.inspect_depth(
                        fp,
                        format="exr",
                        encoding=depth_encoding,
                    )

                typed_read_time, typed_read_peak = _measure(
                    _typed_read, args.runs
                )
                typed_read_rss = _measure_in_process_rss(_typed_read)
                typed_write_time, typed_write_peak = _measure(
                    _typed_write, args.runs
                )
                typed_write_rss = _measure_in_process_rss(_typed_write)
                typed_inspect_time, typed_inspect_peak = _measure(
                    _typed_inspect, args.runs
                )
                typed_inspect_rss = _measure_in_process_rss(_typed_inspect)
                if not np.array_equal(
                    np.asarray(_typed_read().depth).view(np.uint32),
                    depth_values.view(np.uint32),
                ):
                    raise AssertionError("typed EXR depth values differ")
                if Path(typed_path).read_bytes() != typed_bytes:
                    raise AssertionError("typed EXR depth sink bytes differ")
                typed_info = _typed_inspect()
                if (
                    typed_info.shape != depth_values.shape
                    or typed_info.dtype != "float32"
                    or typed_info.metadata.get("stored_dtype") != "float32"
                    or typed_info.metadata.get("channel_name") != "Z"
                ):
                    raise AssertionError("typed EXR depth inspection differs")
                typed_adapter_metrics = {
                    "format": "exr",
                    "read_mbps": typed_mb / typed_read_time,
                    "read_peak_mb": typed_read_peak / 1e6,
                    "read_rss_mb": typed_read_rss / 1e6,
                    "write_mbps": typed_mb / typed_write_time,
                    "write_peak_mb": typed_write_peak / 1e6,
                    "write_rss_mb": typed_write_rss / 1e6,
                    "inspect_ms": typed_inspect_time * 1000,
                    "inspect_peak_mb": typed_inspect_peak / 1e6,
                    "inspect_rss_mb": typed_inspect_rss / 1e6,
                }
            elif s.id == "png":
                typed_side = max(1, int(1024 * args.scale**0.5))
                stored_depth = (
                    (
                        np.arange(
                            typed_side * typed_side,
                            dtype=np.uint32,
                        )
                        * 40503
                    )
                    & 0xFFFF
                ).astype(np.uint16).reshape(typed_side, typed_side)
                depth_values = stored_depth.astype(np.float32)
                depth_encoding = sceneio.DepthEncoding(
                    "millimeters", 0.001, "zero"
                )
                typed_record = _core.depth_map(
                    depth_values,
                    unit="millimeters",
                    invalid_policy="zero",
                )
                typed_source = os.path.join(tmp, "png-depth-source.bin")
                typed_path = os.path.join(tmp, "png-depth-output.bin")
                typed_bytes = bytes(
                    _core.write_png(
                        _core.image(stored_depth, color_space="gray")
                    )
                )
                Path(typed_source).write_bytes(typed_bytes)
                typed_mb = depth_values.nbytes / 1e6

                def _typed_read(fp=typed_source):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.read_depth(
                        fp,
                        format="png",
                        encoding=depth_encoding,
                    )

                def _typed_write(
                    destination=typed_path,
                    value=typed_record,
                ):
                    return sceneio.write_depth(
                        value,
                        destination,
                        format="png",
                        encoding=depth_encoding,
                    )

                def _typed_inspect(fp=typed_source):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.inspect_depth(
                        fp,
                        format="png",
                        encoding=depth_encoding,
                    )

                typed_read_time, typed_read_peak = _measure(
                    _typed_read, args.runs
                )
                typed_read_rss = _measure_in_process_rss(_typed_read)
                typed_write_time, typed_write_peak = _measure(
                    _typed_write, args.runs
                )
                typed_write_rss = _measure_in_process_rss(_typed_write)
                typed_inspect_time, typed_inspect_peak = _measure(
                    _typed_inspect, args.runs
                )
                typed_inspect_rss = _measure_in_process_rss(_typed_inspect)
                if not np.array_equal(
                    np.asarray(_typed_read().depth),
                    depth_values,
                ):
                    raise AssertionError("typed PNG depth values differ")
                if Path(typed_path).read_bytes() != typed_bytes:
                    raise AssertionError("typed PNG depth sink bytes differ")
                typed_info = _typed_inspect()
                if (
                    typed_info.shape != depth_values.shape
                    or typed_info.dtype != "float32"
                    or typed_info.metadata.get("stored_dtype") != "uint16"
                ):
                    raise AssertionError("typed PNG depth inspection differs")
                typed_adapter_metrics = {
                    "format": "png",
                    "read_mbps": typed_mb / typed_read_time,
                    "read_peak_mb": typed_read_peak / 1e6,
                    "read_rss_mb": typed_read_rss / 1e6,
                    "write_mbps": typed_mb / typed_write_time,
                    "write_peak_mb": typed_write_peak / 1e6,
                    "write_rss_mb": typed_write_rss / 1e6,
                    "inspect_ms": typed_inspect_time * 1000,
                    "inspect_peak_mb": typed_inspect_peak / 1e6,
                    "inspect_rss_mb": typed_inspect_rss / 1e6,
                }
            partial_request = _partial_request(s.id, _inspect())
            partial_metrics = None
            if partial_request is not None:

                def _partial_read(
                    fp=fp,
                    codec_id=s.id,
                    request=partial_request,
                ):
                    if args.cold_cache:
                        _evict_file_cache(fp)
                    return sceneio.read_partial(
                        fp, format=codec_id, **request
                    )

                partial_time, partial_peak = _measure(
                    _partial_read, args.runs
                )
                partial_rss = _measure_in_process_rss(_partial_read)
                partial_metrics = (
                    partial_time,
                    partial_peak / 1e6,
                    partial_rss / 1e6,
                )
                partial_rows.append(
                    (
                        s.id,
                        path_time,
                        partial_time,
                        mmap_peak / 1e6,
                        partial_peak / 1e6,
                        mmap_rss / 1e6,
                        partial_rss / 1e6,
                    )
                )

            oraW = oraR = None
            if not args.skip_oracles:
                oraW, oraR = qualification.measure_spec_comparison(
                    s,
                    payload,
                    pmb,
                    args.runs,
                    strict=getattr(args, "strict_oracles", False),
                    measure=_measure,
                    optional_try=_try,
                )

            ratio = (sioR / oraR) if oraR else None
            results.append(
                {
                    "codec": s.id,
                    "payload_mb": pmb,
                    "file_mb": fmb,
                    "write_mbps": sioW,
                    "bytes_path_write_mbps": bytes_path_write,
                    "path_write_mbps": path_write,
                    "read_mbps": sioR,
                    "path_read_mbps": path_read,
                    "oracle_write_mbps": oraW,
                    "oracle_read_mbps": oraR,
                    "bytes_peak_mb": bytes_peak / 1e6,
                    "mmap_peak_mb": mmap_peak / 1e6,
                    "bytes_rss_mb": bytes_rss / 1e6,
                    "mmap_rss_mb": mmap_rss / 1e6,
                    "inspect_ms": inspect_time * 1000,
                    "inspect_peak_mb": inspect_peak / 1e6,
                    "inspect_rss_mb": inspect_rss / 1e6,
                    "partial_ms": (
                        partial_metrics[0] * 1000
                        if partial_metrics is not None
                        else None
                    ),
                    "partial_peak_mb": (
                        partial_metrics[1]
                        if partial_metrics is not None
                        else None
                    ),
                    "partial_rss_mb": (
                        partial_metrics[2]
                        if partial_metrics is not None
                        else None
                    ),
                    "bytes_write_peak_mb": bytes_write_peak / 1e6,
                    "sink_write_peak_mb": sink_write_peak / 1e6,
                    "bytes_write_rss_mb": bytes_write_rss / 1e6,
                    "sink_write_rss_mb": sink_write_rss / 1e6,
                    "o4": o4_metrics or None,
                    "typed_adapter": typed_adapter_metrics,
                    "ply_variants": ply_variant_metrics,
                    "pcd_variants": pcd_variant_metrics,
                    "spz_profiles": spz_profile_metrics,
                }
            )
            print_primary_row(
                s.id,
                pmb,
                fmb,
                sioW,
                sioR,
                path_read,
                oraW,
                oraR,
                bytes_peak / 1e6,
                mmap_peak / 1e6,
                bytes_rss / 1e6,
                mmap_rss / 1e6,
                ratio,
            )
            if typed_adapter_metrics is not None:
                print_typed_adapter(typed_adapter_metrics)
            if ply_variant_metrics is not None:
                print_encoding_variants("PLY", ply_variant_metrics)
            if pcd_variant_metrics is not None:
                print_encoding_variants("PCD", pcd_variant_metrics)
            if spz_profile_metrics is not None:
                print_encoding_variants(
                    "SPZ",
                    spz_profile_metrics,
                    noun="profiles",
                )
        except Exception as e:
            failures.append(s.id)
            results.append({"codec": s.id, "error": f"{type(e).__name__}: {e}"})
            print_primary_error(s.id, e)

    if include_gltf:
        try:
            (
                gltf_result,
                gltf_write_row,
                gltf_inspect_row,
                gltf_partial_row,
                gltf_display,
            ) = _benchmark_gltf(args, tmp)
            results.append(gltf_result)
            write_rows.append(gltf_write_row)
            inspect_rows.append(gltf_inspect_row)
            partial_rows.append(gltf_partial_row)
            (
                payload_mb,
                file_mb,
                write_mbps,
                read_mbps,
                path_read_mbps,
                oracle_write_mbps,
                oracle_read_mbps,
                bytes_peak_mb,
                mmap_peak_mb,
                bytes_rss_mb,
                mmap_rss_mb,
            ) = gltf_display
            ratio = (
                read_mbps / oracle_read_mbps
                if oracle_read_mbps else 0)
            print_primary_row(
                "gltf",
                payload_mb,
                file_mb,
                write_mbps,
                read_mbps,
                path_read_mbps,
                oracle_write_mbps,
                oracle_read_mbps,
                bytes_peak_mb,
                mmap_peak_mb,
                bytes_rss_mb,
                mmap_rss_mb,
                ratio,
            )
        except Exception as e:
            failures.append("gltf")
            results.append(
                {
                    "codec": "gltf",
                    "error": f"{type(e).__name__}: {e}",
                }
            )
            print_primary_error("gltf", e)

    if include_colmap_db:
        try:
            (
                database_result,
                database_write_row,
                database_inspect_row,
                database_partial_rows,
                database_display,
            ) = _benchmark_colmap_db(args, tmp)
            results.append(database_result)
            write_rows.append(database_write_row)
            inspect_rows.append(database_inspect_row)
            partial_rows.extend(database_partial_rows)
            print_colmap_db_row(database_display)
        except Exception as e:
            failures.append("colmap_db")
            results.append(
                {
                    "codec": "colmap_db",
                    "error": f"{type(e).__name__}: {e}",
                }
            )
            print_primary_error("colmap_db", e)

    for spec in path_specs:
        try:
            (
                path_result,
                path_write_row,
                path_inspect_row,
                path_partial_row,
                path_display,
            ) = _benchmark_path_spec(args, tmp, spec)
            results.append(path_result)
            write_rows.append(path_write_row)
            inspect_rows.append(path_inspect_row)
            if path_partial_row is not None:
                partial_rows.append(path_partial_row)
            print_path_row(spec.id, path_display)
        except Exception as e:
            failures.append(spec.id)
            results.append(
                {
                    "codec": spec.id,
                    "error": f"{type(e).__name__}: {e}",
                }
            )
            print_primary_error(spec.id, e)

    for spec in directory_specs:
        try:
            value, payload = spec.make()
            if spec.w is None:
                path = Path(value)
            else:
                path = Path(tmp) / spec.id
                path.mkdir()
                spec.w(value, str(path))
            file_bytes = _directory_size(path)
            payload_bytes = spec.nbytes(value, payload)
            pmb = payload_bytes / 1e6
            fmb = file_bytes / 1e6
            write_time = write_peak = write_rss = None
            if spec.w is not None:
                write_time, write_peak = _measure(
                    lambda: spec.w(value, str(path)), args.runs
                )
                write_rss = _measure_in_process_rss(
                    lambda: spec.w(value, str(path))
                )
                write_rows.append(
                    (
                        spec.id,
                        pmb,
                        fmb,
                        None,
                        pmb / write_time,
                        None,
                        write_peak / 1e6,
                        None,
                        write_rss / 1e6,
                    )
                )

            def _directory_read(path=path, codec_id=spec.id, path_read=spec.path_read):
                if args.cold_cache:
                    for entry in path.iterdir():
                        if entry.is_file():
                            _evict_file_cache(entry)
                if path_read is not None:
                    return path_read(path)
                return sceneio.read(path, format=codec_id)

            core_read_time, _ = _measure(lambda: spec.r(str(path)), args.runs)
            path_read_time, read_peak = _measure(_directory_read, args.runs)
            read_rss = _measure_in_process_rss(_directory_read)

            def _directory_inspect(path=path, codec_id=spec.id):
                if args.cold_cache:
                    for entry in path.iterdir():
                        if entry.is_file():
                            _evict_file_cache(entry)
                return sceneio.inspect(path, format=codec_id)

            inspect_time, inspect_peak = _measure(
                _directory_inspect, args.runs
            )
            inspect_rss = _measure_in_process_rss(_directory_inspect)
            inspect_rows.append(
                (
                    spec.id,
                    path_read_time,
                    inspect_time,
                    read_peak / 1e6,
                    inspect_peak / 1e6,
                    read_rss / 1e6,
                    inspect_rss / 1e6,
                )
            )
            decoded = _directory_read()
            if spec.assert_read is not None:
                spec.assert_read(value, decoded)
            del decoded
            partial_request = _partial_request(
                spec.id, _directory_inspect(), value
            )
            partial_time = partial_peak = partial_rss = None
            if spec.partial is not None or partial_request is not None:

                def _directory_partial(
                    path=path,
                    codec_id=spec.id,
                    request=partial_request,
                    partial=spec.partial,
                ):
                    if args.cold_cache:
                        for entry in path.iterdir():
                            if entry.is_file():
                                _evict_file_cache(entry)
                    if partial is not None:
                        return partial(path)
                    return sceneio.read_partial(
                        path, format=codec_id, **request
                    )

                partial_time, partial_peak = _measure(
                    _directory_partial, args.runs
                )
                partial_rss = _measure_in_process_rss(_directory_partial)
                selected = _directory_partial()
                if spec.assert_partial is not None:
                    spec.assert_partial(value, selected)
                del selected
                partial_rows.append(
                    (
                        spec.id,
                        path_read_time,
                        partial_time,
                        read_peak / 1e6,
                        partial_peak / 1e6,
                        read_rss / 1e6,
                        partial_rss / 1e6,
                    )
                )
            results.append(
                {
                    "codec": spec.id,
                    "payload_mb": pmb,
                    "file_mb": fmb,
                    "write_mbps": (
                        None if write_time is None else pmb / write_time
                    ),
                    "path_write_mbps": (
                        None if write_time is None else pmb / write_time
                    ),
                    "read_mbps": pmb / core_read_time,
                    "path_read_mbps": pmb / path_read_time,
                    "mmap_peak_mb": read_peak / 1e6,
                    "mmap_rss_mb": read_rss / 1e6,
                    "inspect_ms": inspect_time * 1000,
                    "inspect_peak_mb": inspect_peak / 1e6,
                    "inspect_rss_mb": inspect_rss / 1e6,
                    "partial_ms": (
                        None
                        if partial_time is None
                        else partial_time * 1000
                    ),
                    "partial_peak_mb": (
                        None
                        if partial_peak is None
                        else partial_peak / 1e6
                    ),
                    "partial_rss_mb": (
                        None
                        if partial_rss is None
                        else partial_rss / 1e6
                    ),
                    "sink_write_peak_mb": (
                        None if write_peak is None else write_peak / 1e6
                    ),
                    "sink_write_rss_mb": (
                        None if write_rss is None else write_rss / 1e6
                    ),
                }
            )
            print_directory_row(
                spec.id,
                pmb,
                fmb,
                0.0 if write_time is None else pmb / write_time,
                pmb / core_read_time,
                pmb / path_read_time,
                read_peak / 1e6,
                read_rss / 1e6,
            )
        except Exception as e:
            failures.append(spec.id)
            results.append({"codec": spec.id, "error": f"{type(e).__name__}: {e}"})
            print_primary_error(spec.id, e)

    if not args.only:
        assert (
            len(specs)
            + len(directory_specs)
            + len(path_specs)
            + int(include_colmap_db)
            + int(include_gltf)
            == len(qualification.COMPARISON_QUALIFICATIONS)
        )
    if getattr(args, "strict_oracles", False):
        qualification.validate_strict_results(results)
    print_summary(write_rows, o4_rows, inspect_rows, partial_rows)
    if args.require_o5_inspect_gains:
        stable = {
            "exr",
            "gaussian_ply",
            "las",
            "laz",
            "off",
            "png",
            "spz",
            "stl",
            "y4m",
        }
        by_codec = {
            codec_id: (
                full,
                inspected,
                inspected_peak,
                full_rss,
                inspected_rss,
            )
            for (
                codec_id,
                full,
                inspected,
                _,
                inspected_peak,
                full_rss,
                inspected_rss,
            ) in inspect_rows
        }
        missing = stable - by_codec.keys()
        if missing:
            raise RuntimeError(
                "missing O5 inspect guard rows: " + ", ".join(sorted(missing))
            )
        regressions = [
            codec_id
            for codec_id in sorted(stable)
            if by_codec[codec_id][1] >= by_codec[codec_id][0]
        ]
        if regressions:
            raise RuntimeError(
                "O5 inspection failed directional latency guard: "
                + ", ".join(regressions)
            )
        json_controls = {"transforms_json", "openmvg"}
        missing_json = json_controls - by_codec.keys()
        if missing_json:
            raise RuntimeError(
                "missing O5 JSON read-control rows: "
                + ", ".join(sorted(missing_json))
            )
        json_read_regressions = sorted(
            codec_id
            for codec_id in json_controls
            if by_codec[codec_id][0] > 3.0 * by_codec[codec_id][1]
        )
        if json_read_regressions:
            raise RuntimeError(
                "O5 full JSON read exceeded 3x its independent metadata "
                "parser control: "
                + ", ".join(json_read_regressions)
            )
        qualification.validate_o5_allocation_controls(
            "inspection",
            {
                codec_id: (full_peak, inspected_peak)
                for (
                    codec_id,
                    _,
                    _,
                    full_peak,
                    inspected_peak,
                    _,
                    _,
                ) in inspect_rows
            },
            directional_limits=(
                qualification.O5_INSPECTION_DIRECTIONAL_ALLOCATION_LIMITS
            ),
        )
        rss_regressions = sorted(
            codec_id
            for codec_id, (_, _, _, full_rss, inspected_rss) in by_codec.items()
            if inspected_rss > max(8.0, full_rss + 4.0)
        )
        if rss_regressions:
            raise RuntimeError(
                "O5 inspection exceeded the sampled RSS guard: "
                + ", ".join(rss_regressions)
            )
        rss_gain_regressions = sorted(
            codec_id
            for codec_id in stable
            if by_codec[codec_id][3] >= 8.0
            and by_codec[codec_id][4]
            >= max(4.0, 0.5 * by_codec[codec_id][3])
        )
        if rss_gain_regressions:
            raise RuntimeError(
                "O5 inspection failed the directional RSS gain guard: "
                + ", ".join(rss_gain_regressions)
            )
    if args.require_o5_partial_gains:
        stable = {
            "pfm",
            "netpbm",
            "webp",
            "xyz",
            "ply_mesh",
            "stl",
            "off",
            "las",
            "laz",
            "gaussian_ply",
            "splat",
            "colmap_sparse",
            "colmap_sparse_txt",
            "y4m",
        }
        by_codec = {
            codec_id: (
                full,
                partial_time,
                part_peak,
                full_rss,
                part_rss,
            )
            for (
                codec_id,
                full,
                partial_time,
                _,
                part_peak,
                full_rss,
                part_rss,
            ) in partial_rows
        }
        missing = stable - by_codec.keys()
        if missing:
            raise RuntimeError(
                "missing O5 partial guard rows: " + ", ".join(sorted(missing))
            )
        regressions = sorted(
            codec_id
            for codec_id in stable
            if by_codec[codec_id][1] >= by_codec[codec_id][0]
        )
        if regressions:
            raise RuntimeError(
                "O5 partial read failed directional latency guard: "
                + ", ".join(regressions)
            )
        qualification.validate_o5_allocation_controls(
            "partial read",
            {
                codec_id: (full_peak, part_peak)
                for (
                    codec_id,
                    _,
                    _,
                    full_peak,
                    part_peak,
                    _,
                    _,
                ) in partial_rows
            },
            directional_limits=(
                qualification.O5_PARTIAL_DIRECTIONAL_ALLOCATION_LIMITS
            ),
        )
        rss_gain_regressions = sorted(
            codec_id
            for codec_id in stable - {"xyz", "ply_mesh"}
            if by_codec[codec_id][3] >= 8.0
            and by_codec[codec_id][4]
            >= max(4.0, 0.5 * by_codec[codec_id][3])
        )
        # XYZ must scan every mapped line to validate record boundaries. Linux
        # therefore charges the whole file to RSS, while warmed allocator reuse
        # can make the full record's output vector invisible to this delta.
        # Bound resident growth above the unavoidable file mapping instead of
        # comparing two platform-dependent deltas. The selected vector is under
        # 1 MB here, so 8 MB allows page/allocator granularity but not a full
        # 12 MB output materialization.
        xyz_file_mb = next(
            result["file_mb"]
            for result in results
            if result.get("codec") == "xyz" and "file_mb" in result
        )
        if by_codec["xyz"][4] > xyz_file_mb + 8.0:
            rss_gain_regressions.append("xyz")
        # A mesh face selection validates the complete mapped file and retains
        # the complete vertex domain by contract. The benchmark's vertex-domain
        # output is about 12 MB, so allow the file mapping plus 20 MB of record
        # and allocator overhead while still rejecting full corner-domain
        # materialization.
        mesh_file_mb = next(
            result["file_mb"]
            for result in results
            if result.get("codec") == "ply_mesh" and "file_mb" in result
        )
        if by_codec["ply_mesh"][4] > mesh_file_mb + 20.0:
            rss_gain_regressions.append("ply_mesh")
        if rss_gain_regressions:
            raise RuntimeError(
                "O5 partial read failed the directional RSS gain guard: "
                + ", ".join(rss_gain_regressions)
            )
    if args.require_o4_gains:
        guarded = {
            ("webp", "balanced-config"),
            ("webp", "workers-palette"),
            ("xyz", "format-write"),
            ("las", "points-write"),
            ("las", "points-read"),
        }
        measured = {
            (codec_id, operation): (base, optimized)
            for codec_id, operation, base, optimized, _ in o4_rows
        }
        for key in sorted(guarded):
            base, optimized = measured[key]
            if optimized <= base:
                failures.append(f"o4-regression:{key[0]}:{key[1]}")

        for result in results:
            if "error" in result or "bytes_peak_mb" not in result:
                continue
            bytes_peak = result["bytes_peak_mb"]
            mmap_peak = result["mmap_peak_mb"]
            if bytes_peak >= 0.5 and mmap_peak >= bytes_peak * 0.25:
                failures.append(
                    f"mmap-memory-regression:{result['codec']}"
                )
            bytes_write_peak = result["bytes_write_peak_mb"]
            sink_write_peak = result["sink_write_peak_mb"]
            if (
                bytes_write_peak >= 0.5
                and sink_write_peak >= bytes_write_peak * 0.25
            ):
                failures.append(
                    f"sink-memory-regression:{result['codec']}"
                )
        if not failures:
            print_regression_guard_passed()
    if args.cold_cache and not (
        hasattr(os, "posix_fadvise") and hasattr(os, "POSIX_FADV_DONTNEED")
    ):
        print_cold_cache_unavailable()
    return failures, results


if __name__ == "__main__":
    main()
