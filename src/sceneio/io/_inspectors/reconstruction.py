"""Metadata-only inspection for reconstruction, pose, graph, and match formats."""

from __future__ import annotations

import struct
from pathlib import Path

from sceneio import _core
from sceneio.io._inspectors.common import (
    _HEADER_LIMIT,
    _compiled_buffer_inspect,
    _exact,
)
from sceneio.io._inspectors.model import (
    ArrayInspection,
    Inspection,
    MetadataValue,
)


def _size(path: Path) -> int:
    return path.stat().st_size


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.iterdir() if item.is_file())


def _iter_data_lines(path: Path):
    with path.open("rb") as stream:
        while line := stream.readline(_HEADER_LIMIT + 2):
            content_size = len(line) - int(line.endswith(b"\n"))
            if content_size > _HEADER_LIMIT:
                raise ValueError("metadata line exceeds 1 MiB")
            stripped = line.strip()
            if stripped and not stripped.startswith(b"#"):
                yield stripped


def inspect_colmap_db(path: Path, datatype: str) -> Inspection:
    """Inspect SQL metadata without fetching any feature/match BLOB."""

    values = _core.inspect_colmap_db(str(path))
    arrays = []
    for (
        image_id,
        keypoint_count,
        keypoint_dim,
        descriptor_count,
        descriptor_dim,
        descriptor_dtype,
    ) in zip(
        values["image_ids"],
        values["keypoint_counts"],
        values["keypoint_dimensions"],
        values["descriptor_counts"],
        values["image_descriptor_dimensions"],
        values["image_descriptor_dtypes"],
        strict=True,
    ):
        if keypoint_count >= 0:
            arrays.append(
                ArrayInspection(
                    f"{image_id}/keypoints",
                    (keypoint_count, keypoint_dim),
                    "float32",
                )
            )
        if descriptor_count >= 0:
            arrays.append(
                ArrayInspection(
                    f"{image_id}/descriptors",
                    (descriptor_count, descriptor_dim),
                    descriptor_dtype,
                )
            )
    metadata: dict[str, MetadataValue] = {
        "user_version": values["user_version"],
        "sqlite_version": values["sqlite_version"],
        "num_rigs": values["num_rigs"],
        "num_rig_sensors": values["num_rig_sensors"],
        "num_frames": values["num_frames"],
        "num_frame_data": values["num_frame_data"],
        "num_pose_priors": values["num_pose_priors"],
        "pose_prior_layout": values["pose_prior_layout"],
        "num_keypoint_color_rows": values["num_keypoint_color_rows"],
        "num_match_score_pairs": values["num_match_score_pairs"],
        "num_image_qualities": values["num_image_qualities"],
        "num_pair_provenance": values["num_pair_provenance"],
        "num_markers": values["num_markers"],
        "num_marker_projections": values["num_marker_projections"],
        "num_videos": values["num_videos"],
        "num_video_frames": values["num_video_frames"],
        "num_cameras": values["num_cameras"],
        "num_images": values["num_images"],
        "num_keypoint_rows": values["num_keypoint_rows"],
        "num_descriptor_rows": values["num_descriptor_rows"],
        "num_match_pairs": values["num_match_pairs"],
        "num_verified_pairs": values["num_verified_pairs"],
        "num_matches": values["num_matches"],
        "num_verified_matches": values["num_verified_matches"],
        "descriptor_dimensions": tuple(values["descriptor_dimensions"]),
        "image_ids": tuple(values["image_ids"]),
        "image_names": tuple(values["image_names"]),
    }
    if values["maxx_schema_info_present"]:
        metadata.update(
            {
                "maxx_schema_version": values["maxx_schema_version"],
                "maxx_minimum_reader_version": values[
                    "maxx_minimum_reader_version"
                ],
                "maxx_producer_version": values["maxx_producer_version"],
                "maxx_producer_commit": values["maxx_producer_commit"],
            }
        )
    return Inspection(
        format="colmap_db",
        datatype=datatype,
        byte_size=_size(path),
        shape=(values["num_images"],),
        count=values["num_images"],
        arrays=tuple(arrays),
        metadata=metadata,
    )


def inspect_pose_text(
    path: Path,
    format_id: str,
    datatype: str,
) -> Inspection:
    expected = 8 if format_id == "tum" else 12
    count = 0
    for line in _iter_data_lines(path):
        if len(line.split(maxsplit=expected)) < expected:
            raise ValueError(f"{format_id}: expected at least {expected} fields per data line")
        count += 1
    return Inspection(
        format_id,
        datatype,
        _size(path),
        shape=(count,),
        dtype="float64",
        count=count,
    )


def inspect_euroc_state(path: Path, datatype: str) -> Inspection:
    count, first_timestamp, last_timestamp = _compiled_buffer_inspect(
        path, _core._inspect_euroc_state
    )
    metadata: dict[str, MetadataValue] = {
        "timestamp_unit": "nanoseconds",
        "quaternion_order": "wxyz",
        "quaternion_sign": "preserved",
        "pose_convention": "sensor_to_reference",
        "position_frame": "reference",
        "velocity_frame": "reference",
        "bias_frame": "sensor",
        "position_unit": "meters",
        "velocity_unit": "meters_per_second",
        "gyro_bias_unit": "radians_per_second",
        "accel_bias_unit": "meters_per_second_squared",
    }
    if count:
        metadata["first_timestamp_ns"] = first_timestamp
        metadata["last_timestamp_ns"] = last_timestamp
    return Inspection(
        "euroc_state",
        datatype,
        _size(path),
        shape=(count,),
        dtype="float64",
        count=count,
        metadata=metadata,
    )


def inspect_g2o(path: Path, datatype: str) -> Inspection:
    nodes, edges, fixed = _compiled_buffer_inspect(path, _core._inspect_g2o)
    return Inspection(
        "g2o",
        datatype,
        _size(path),
        shape=(nodes,),
        dtype="float64",
        count=nodes,
        metadata={
            "num_nodes": nodes,
            "num_edges": edges,
            "num_fixed_nodes": fixed,
            "quaternion_order": "xyzw",
            "quaternion_sign": "preserved",
            "node_transform_convention": "node_to_reference",
            "edge_transform_convention": "source_inverse_times_target",
            "translation_unit": "unspecified",
            "information_variable_order": "tx_ty_tz_qx_qy_qz",
        },
    )


def inspect_bundler(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    cameras, points = _compiled_buffer_inspect(
        path, _core._inspect_bundler
    )
    return Inspection(
        "bundler",
        datatype,
        file_size,
        shape=(cameras,),
        dtype="float64",
        count=cameras,
        metadata={
            "num_cameras": cameras,
            "num_images": cameras,
            "num_points3D": points,
        },
    )


def inspect_bal(path: Path, datatype: str) -> Inspection:
    cameras, points, observations = _compiled_buffer_inspect(
        path, _core._inspect_bal
    )
    return Inspection(
        "bal",
        datatype,
        _size(path),
        shape=(cameras,),
        dtype="float64",
        count=cameras,
        metadata={
            "num_cameras": cameras,
            "num_images": cameras,
            "num_points3D": points,
            "num_observations": observations,
        },
    )


def inspect_nvm(path: Path, datatype: str) -> Inspection:
    cameras, points = _compiled_buffer_inspect(path, _core._inspect_nvm)
    return Inspection(
        "nvm",
        datatype,
        _size(path),
        shape=(cameras,),
        dtype="float64",
        count=cameras,
        metadata={
            "num_cameras": cameras,
            "num_images": cameras,
            "num_points3D": points,
        },
    )


def inspect_transforms(path: Path, datatype: str) -> Inspection:
    views, cameras = _compiled_buffer_inspect(
        path, _core._inspect_transforms_json
    )
    return Inspection(
        "transforms_json",
        datatype,
        _size(path),
        shape=(views,),
        dtype="float64",
        count=views,
        metadata={"num_views": views, "num_cameras": cameras},
    )


def inspect_openmvg(path: Path, datatype: str) -> Inspection:
    cameras, images, points = _compiled_buffer_inspect(
        path, _core._inspect_openmvg
    )
    return Inspection(
        "openmvg",
        datatype,
        _size(path),
        shape=(images,),
        dtype="float64",
        count=images,
        metadata={
            "num_cameras": cameras,
            "num_images": images,
            "num_points3D": points,
        },
    )


def inspect_colmap_binary(path: Path, datatype: str) -> Inspection:
    counts = {}
    for filename, key in (
        ("cameras.bin", "num_cameras"),
        ("images.bin", "num_images"),
        ("points3D.bin", "num_points3D"),
    ):
        with (path / filename).open("rb") as stream:
            counts[key] = struct.unpack("<Q", _exact(stream, 8, filename))[0]
    return Inspection(
        "colmap_sparse",
        datatype,
        _directory_size(path),
        shape=(counts["num_images"],),
        dtype="float64",
        count=counts["num_images"],
        metadata=counts,
    )


def inspect_colmap_text(path: Path, datatype: str) -> Inspection:
    cameras, images, points = _core._inspect_colmap_txt(str(path))
    counts = {
        "num_cameras": cameras,
        "num_images": images,
        "num_points3D": points,
    }
    return Inspection(
        "colmap_sparse_txt",
        datatype,
        _directory_size(path),
        shape=(counts["num_images"],),
        dtype="float64",
        count=counts["num_images"],
        metadata=counts,
    )
