"""Private native-storage bridge for the canonical correspondence graph.

Codecs use this module to translate their ragged numeric storage. It is not a
public representation adapter: callers always receive and provide
``sceneio.CorrespondenceGraph``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence

import numpy as np

from sceneio import _core
from sceneio._data.features import (
    CorrespondenceGraph,
    PairCorrespondences,
    TwoViewGeometry,
)
from sceneio._data.transforms import SE3
from sceneio.errors import ContractViolation


def _names_by_id(value: Mapping[int, str] | Sequence[str]) -> dict[int, str]:
    if isinstance(value, Mapping):
        result = dict(value)
    else:
        result = {index + 1: name for index, name in enumerate(value)}
    if any(
        isinstance(image_id, bool)
        or not isinstance(image_id, int)
        or image_id < 0
        or not isinstance(name, str)
        or not name
        for image_id, name in result.items()
    ):
        raise ContractViolation("correspondence image ids and names are invalid")
    if len(result.values()) != len(set(result.values())):
        raise ContractViolation("correspondence image names must be unique")
    return result


def graph_from_storage(
    storage: object,
    *,
    features: Mapping[str, object] | None = None,
    image_names: Mapping[int, str] | Sequence[str],
) -> CorrespondenceGraph:
    """Materialize both native channels without discarding source metadata."""

    if not isinstance(storage, _core.CorrespondenceStorage):
        raise TypeError("correspondence storage has an unexpected native type")
    names = _names_by_id(image_names)
    feature_values = {} if features is None else dict(features)
    raw_pairs: dict[tuple[str, str], PairCorrespondences] = {}
    verified_pairs: dict[tuple[str, str], PairCorrespondences] = {}
    configurations: dict[tuple[str, str], int] = {}
    relative_poses: dict[tuple[str, str], SE3] = {}
    metadata: dict[tuple[str, str], dict[str, object]] = {}

    image_pairs = np.asarray(storage.image_pairs)
    raw_offsets = np.asarray(storage.match_offsets)
    raw_matches = np.asarray(storage.matches)
    raw_scores = None if storage.scores is None else np.asarray(storage.scores)
    verified_offsets = np.asarray(storage.verified_offsets)
    verified_matches = np.asarray(storage.verified_matches)
    match_present = np.asarray(storage.match_present)
    geometry_present = np.asarray(storage.geometry_present)
    score_present = np.asarray(storage.match_score_present)
    f_present = np.asarray(storage.F_present)
    e_present = np.asarray(storage.E_present)
    h_present = np.asarray(storage.H_present)
    fundamental = np.asarray(storage.fundamental_matrices)
    essential = np.asarray(storage.essential_matrices)
    homographies = np.asarray(storage.homographies)
    pose_present = np.asarray(storage.pose_present)
    qvecs = np.asarray(storage.qvecs)
    tvecs = np.asarray(storage.tvecs)
    provenance_present = np.asarray(storage.provenance_present)
    source_flags = np.asarray(storage.source_flags)
    retrieval_present = np.asarray(storage.retrieval_score_present)
    retrieval_scores = np.asarray(storage.retrieval_scores)
    camera1_present = np.asarray(storage.camera1_present)
    camera2_present = np.asarray(storage.camera2_present)
    camera1_prior = np.asarray(storage.camera1_prior_focal_length)
    camera2_prior = np.asarray(storage.camera2_prior_focal_length)
    recovered_camera1_ids = tuple(storage.recovered_camera1_ids)
    recovered_camera2_ids = tuple(storage.recovered_camera2_ids)

    for index, endpoints in enumerate(image_pairs):
        image_id1, image_id2 = (int(endpoints[0]), int(endpoints[1]))
        try:
            key = (names[image_id1], names[image_id2])
        except KeyError as exc:
            raise ContractViolation(
                f"correspondence pair references unnamed image id {int(exc.args[0])}"
            ) from None
        if key in raw_pairs or key in verified_pairs:
            raise ContractViolation(f"duplicate correspondence pair {key!r}")

        raw_start, raw_stop = int(raw_offsets[index]), int(raw_offsets[index + 1])
        verified_start = int(verified_offsets[index])
        verified_stop = int(verified_offsets[index + 1])
        if bool(match_present[index]):
            scores = None
            if raw_scores is not None and bool(score_present[index]):
                scores = raw_scores[raw_start:raw_stop]
            raw_pairs[key] = PairCorrespondences.from_indices(
                raw_matches[raw_start:raw_stop],
                scores=scores,
            )

        geometry = None
        if bool(geometry_present[index]):
            geometry = TwoViewGeometry(
                E=essential[index] if bool(e_present[index]) else None,
                F=fundamental[index] if bool(f_present[index]) else None,
                H=homographies[index] if bool(h_present[index]) else None,
                num_inliers=verified_stop - verified_start,
            )
            verified_pairs[key] = PairCorrespondences.from_indices(
                verified_matches[verified_start:verified_stop],
                geometry=geometry,
            )

        if key not in raw_pairs and key not in verified_pairs:
            raw_pairs[key] = PairCorrespondences.from_indices(
                np.empty((0, 2), dtype=np.uint32)
            )

        configurations[key] = int(np.asarray(storage.configs)[index])
        if bool(pose_present[index]):
            relative_poses[key] = SE3.from_quaternion_wxyz(
                qvecs[index],
                tvecs[index],
                convention="opencv_second_from_first",
            )

        pair_metadata: dict[str, object] = {
            "image_ids": (image_id1, image_id2),
            "match_row_present": bool(match_present[index]),
            "geometry_row_present": bool(geometry_present[index]),
            "match_score_row_present": bool(score_present[index]),
        }
        if key in raw_pairs and not bool(match_present[index]):
            pair_metadata["synthetic_absent_pair"] = True
        if bool(provenance_present[index]):
            pair_metadata["source_flags"] = int(source_flags[index])
        if bool(retrieval_present[index]):
            pair_metadata["retrieval_score"] = float(retrieval_scores[index])
        if bool(camera1_present[index]):
            pair_metadata["recovered_camera1_id"] = int(recovered_camera1_ids[index])
            pair_metadata["recovered_camera1"] = storage.recovered_camera1(index)
            pair_metadata["camera1_prior_focal_length"] = bool(camera1_prior[index])
        if bool(camera2_present[index]):
            pair_metadata["recovered_camera2_id"] = int(recovered_camera2_ids[index])
            pair_metadata["recovered_camera2"] = storage.recovered_camera2(index)
            pair_metadata["camera2_prior_focal_length"] = bool(camera2_prior[index])
        metadata[key] = pair_metadata

    endpoint_names = {name for key in raw_pairs | verified_pairs for name in key}
    validation = "eager" if endpoint_names.issubset(feature_values) else "deferred"
    graph = CorrespondenceGraph(
        feature_values,
        raw_pairs,
        verified_pairs,
        configurations,
        relative_poses,
        metadata,
        index_validation=validation,
    )
    object.__setattr__(graph, "_storage", storage)
    return graph


def graph_from_colmap_database(database: object) -> CorrespondenceGraph:
    """Build the canonical graph view of a native COLMAP aggregate."""

    if not isinstance(database, _core.ColmapDatabase):
        raise TypeError("value must be ColmapDatabase")
    names: dict[int, str] = {}
    features: dict[str, object] = {}
    for index in range(database.num_images):
        feature = database.feature_at(index)
        names[int(feature.image_id)] = feature.image_name
        features[feature.image_name] = feature
    for endpoints in np.asarray(database._correspondence_storage.image_pairs):
        for image_id in endpoints:
            names.setdefault(int(image_id), str(int(image_id)))
    return graph_from_storage(
        database._correspondence_storage,
        features=features,
        image_names=names,
    )


def read_colmap_database_pair(path: str, image_id1: int, image_id2: int) -> CorrespondenceGraph:
    """Read one pair and resolve persisted numeric ids to canonical names."""

    storage = _core.read_colmap_db_pair(path, image_id1, image_id2)
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as database:
        rows = database.execute(
            "SELECT image_id, name FROM images WHERE image_id IN (?1, ?2)",
            (image_id1, image_id2),
        ).fetchall()
    names = {int(image_id): str(name) for image_id, name in rows}
    names.setdefault(image_id1, str(image_id1))
    names.setdefault(image_id2, str(image_id2))
    return graph_from_storage(storage, image_names=names)


def storage_from_graph(
    graph: CorrespondenceGraph,
    *,
    image_ids: Mapping[str, int],
) -> object:
    """Build native ragged storage for a codec that needs numeric ids."""

    if not isinstance(graph, CorrespondenceGraph):
        raise TypeError("value must be CorrespondenceGraph")
    if graph._storage is not None:
        return graph._storage
    ids = dict(image_ids)
    keys = list(graph.pairs)
    keys.extend(key for key in graph.verified_pairs if key not in graph.pairs)
    if any(name not in ids for key in keys for name in key):
        raise ContractViolation("a correspondence pair has no numeric image id")

    image_pair_rows: list[tuple[int, int]] = []
    raw_rows: list[np.ndarray] = []
    verified_rows: list[np.ndarray] = []
    raw_offsets = [0]
    verified_offsets = [0]
    score_rows: list[np.ndarray] = []
    score_present: list[int] = []
    configs: list[int] = []
    f_values: list[np.ndarray] = []
    e_values: list[np.ndarray] = []
    h_values: list[np.ndarray] = []
    f_present: list[int] = []
    e_present: list[int] = []
    h_present: list[int] = []
    qvecs: list[np.ndarray] = []
    tvecs: list[np.ndarray] = []
    pose_present: list[int] = []
    match_present: list[int] = []
    geometry_present: list[int] = []

    for key in keys:
        id1, id2 = ids[key[0]], ids[key[1]]
        if id1 >= id2:
            raise ContractViolation(
                f"correspondence pair {key!r} must map to increasing numeric ids"
            )
        image_pair_rows.append((id1, id2))
        raw = graph.pairs.get(key)
        verified = graph.verified_pairs.get(key)
        for label, pair in (("raw", raw), ("verified", verified)):
            if pair is not None and pair.mode != "indexed":
                raise ContractViolation(
                    f"native {label} correspondence pair {key!r} must be indexed"
                )
        raw_indices = (
            np.empty((0, 2), dtype=np.uint32)
            if raw is None
            else np.ascontiguousarray(raw.indices, dtype=np.uint32)
        )
        verified_indices = (
            np.empty((0, 2), dtype=np.uint32)
            if verified is None
            else np.ascontiguousarray(verified.indices, dtype=np.uint32)
        )
        raw_rows.append(raw_indices)
        verified_rows.append(verified_indices)
        raw_offsets.append(raw_offsets[-1] + len(raw_indices))
        verified_offsets.append(verified_offsets[-1] + len(verified_indices))
        match_present.append(int(raw is not None))
        geometry_present.append(int(verified is not None))
        if verified is not None and verified.scores is not None:
            raise ContractViolation("verified correspondence scores are not representable")
        if raw is not None and raw.scores is not None:
            score_rows.append(np.ascontiguousarray(raw.scores))
            score_present.append(1)
        else:
            score_rows.append(np.zeros(len(raw_indices), dtype=np.float32))
            score_present.append(0)

        geometry = None if verified is None else verified.geometry
        if geometry is None and raw is not None:
            geometry = raw.geometry
        for value, values, present in (
            (None if geometry is None else geometry.F, f_values, f_present),
            (None if geometry is None else geometry.E, e_values, e_present),
            (None if geometry is None else geometry.H, h_values, h_present),
        ):
            values.append(np.zeros((3, 3), dtype=np.float64) if value is None else value)
            present.append(int(value is not None))
        configs.append(graph.configurations.get(key, 0))
        pose = graph.relative_poses.get(key)
        if pose is None:
            qvecs.append(np.zeros(4, dtype=np.float64))
            tvecs.append(np.zeros(3, dtype=np.float64))
            pose_present.append(0)
        else:
            qvecs.append(pose.to_quaternion_wxyz())
            tvecs.append(pose.translation)
            pose_present.append(1)

    pair_count = len(keys)
    empty = np.empty((0, 2), dtype=np.uint32)
    raw_values = np.concatenate(raw_rows) if raw_rows else empty
    verified_values = np.concatenate(verified_rows) if verified_rows else empty
    scores = np.concatenate(score_rows) if any(score_present) else None
    return _core.correspondence_storage(
        np.asarray(image_pair_rows, dtype=np.uint32).reshape(pair_count, 2),
        np.asarray(raw_offsets, dtype=np.uint64),
        raw_values,
        np.asarray(verified_offsets, dtype=np.uint64),
        verified_values,
        scores=scores,
        configs=np.asarray(configs, dtype=np.int32),
        fundamental_matrices=np.asarray(f_values, dtype=np.float64).reshape(pair_count, 3, 3),
        fundamental_present=np.asarray(f_present, dtype=np.uint8),
        essential_matrices=np.asarray(e_values, dtype=np.float64).reshape(pair_count, 3, 3),
        essential_present=np.asarray(e_present, dtype=np.uint8),
        homographies=np.asarray(h_values, dtype=np.float64).reshape(pair_count, 3, 3),
        homography_present=np.asarray(h_present, dtype=np.uint8),
        qvecs=np.asarray(qvecs, dtype=np.float64).reshape(pair_count, 4),
        tvecs=np.asarray(tvecs, dtype=np.float64).reshape(pair_count, 3),
        pose_present=np.asarray(pose_present, dtype=np.uint8),
        match_present=np.asarray(match_present, dtype=np.uint8),
        geometry_present=np.asarray(geometry_present, dtype=np.uint8),
        match_score_present=np.asarray(score_present, dtype=np.uint8),
    )


__all__: list[str] = []
