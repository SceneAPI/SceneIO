"""Built-in reconstruction, pose, state, and graph codec definitions."""

from __future__ import annotations

from sceneio import _core
from sceneio.io._registry.adapters import (
    _file_sink_writer,
    _mmap_reader,
    _mmap_selector_reader,
)
from sceneio.io._registry.model import Codec

RECONSTRUCTION_CODECS: tuple[Codec, ...] = (
    Codec(
        "colmap_sparse",
        (),
        _core.read_colmap_sparse,
        _core.write_colmap_sparse,
        record=_core.Reconstruction,
        datatype="sparse_model",
        is_directory=True,
        read_image=_core.read_colmap_sparse_image,
        supported_features=("cameras", "images", "points3D", "tracks"),
    ),
    # Camera-pose formats -> PosedViewSet. `datatype` here is informational; a
    # vocabulary id is pending, like `splat` (see formats/datatypes.py).
    Codec(
        "transforms_json",
        (),
        _mmap_reader(_core.read_transforms_json),
        _file_sink_writer(_core.write_transforms_json),
        record=_core.PosedViewSet,
        datatype="posed_views",
        filenames=("transforms.json",),
    ),
    # TUM/KITTI claim no extension (`.txt` is ambiguous), so they are
    # explicit-`format=` only.
    Codec(
        "tum",
        (),
        _mmap_reader(_core.read_tum),
        _file_sink_writer(_core.write_tum),
        record=_core.PosedViewSet,
        datatype="posed_views",
    ),
    Codec(
        "kitti",
        (),
        _mmap_reader(_core.read_kitti),
        _file_sink_writer(_core.write_kitti),
        record=_core.PosedViewSet,
        datatype="posed_views",
    ),
    Codec(
        "euroc_state",
        (),
        _mmap_reader(_core.read_euroc_state),
        _file_sink_writer(_core.write_euroc_state),
        record=_core.StateTrajectory,
        datatype="state_trajectory",
        magic=(b"#timestamp [ns],",),
        read_states=_mmap_selector_reader(
            _core.read_euroc_state_states
        ),
        supported_features=(
            "int64_nanosecond_timestamps",
            "position",
            "wxyz_orientation",
            "velocity",
            "gyroscope_bias",
            "accelerometer_bias",
            "state_ranges",
        ),
    ),
    Codec(
        "g2o",
        (".g2o",),
        _mmap_reader(_core.read_g2o),
        _file_sink_writer(_core.write_g2o),
        record=_core.PoseGraph,
        datatype="pose_graph",
        magic=(
            b"# g2o pose graph",
            b"VERTEX_SE3:QUAT",
            b"EDGE_SE3:QUAT",
        ),
        supported_features=(
            "vertex_se3_quat",
            "edge_se3_quat",
            "fixed_vertices",
            "symmetric_information_6x6",
        ),
        unsupported_features=(
            "mixed_vertex_types",
            "mixed_edge_types",
            "parameters",
            "robust_kernels",
        ),
    ),
    Codec(
        "colmap_db",
        (".db",),
        _core.read_colmap_db,
        _core.write_colmap_db,
        record=_core.ColmapDatabase,
        datatype="match_graph",
        magic=(b"SQLite format 3\x00",),
        filenames=("database.db",),
        read_image=_core.read_colmap_db_image,
        read_pair=_core.read_colmap_db_pair,
        supported_features=(
            "cameras",
            "images",
            "keypoints_2_4_6",
            "uint8_descriptors",
            "extractor_type",
            "raw_matches",
            "verified_matches",
            "F_E_H",
            "relative_pose",
            "sparse_ids",
            "current_recovered_camera_reads",
            "stock_rig_frame_reads",
            "stock_pose_prior_reads",
            "read_only_reads",
            "transactional_writes",
        ),
        unsupported_features=(
            "rig_frame_writes",
            "pose_prior_writes",
            "scores",
            "float_descriptors",
            "maxx_extension_fields",
        ),
    ),
    # COLMAP text sparse (cameras.txt/images.txt/points3D.txt) is the text twin
    # of colmap_sparse, distinguished by its cameras.txt directory marker.
    Codec(
        "colmap_sparse_txt",
        (),
        _core.read_colmap_txt,
        _core.write_colmap_txt,
        record=_core.Reconstruction,
        datatype="sparse_model",
        is_directory=True,
        dir_marker="cameras.txt",
        read_image=_core.read_colmap_txt_image,
        supported_features=("cameras", "images", "points3D", "tracks"),
    ),
    # SfM pose formats -> Reconstruction, convention-converted to
    # WXYZ/world_to_camera.
    Codec(
        "bundler",
        (".out",),
        _mmap_reader(_core.read_bundler),
        _file_sink_writer(_core.write_bundler),
        record=_core.Reconstruction,
        datatype="sparse_model",
        magic=(b"# Bundle file",),
    ),
    Codec(
        "bal",
        (".bal",),
        _mmap_reader(_core.read_bal),
        _file_sink_writer(_core.write_bal),
        record=_core.Reconstruction,
        datatype="sparse_model",
        supported_features=(
            "angle_axis",
            "radial_k1_k2",
            "centered_observations",
            "deterministic_17_digit_writer",
        ),
        unsupported_features=(
            "bzip2",
            "image_names",
            "image_dimensions",
            "principal_points",
            "point_colors",
            "point_errors",
            "untriangulated_observations",
        ),
    ),
    Codec(
        "nvm",
        (".nvm",),
        _mmap_reader(_core.read_nvm),
        _file_sink_writer(_core.write_nvm),
        record=_core.Reconstruction,
        datatype="sparse_model",
        magic=(b"NVM_V3",),
    ),
    Codec(
        "openmvg",
        (),
        _mmap_reader(_core.read_openmvg),
        _file_sink_writer(_core.write_openmvg),
        record=_core.Reconstruction,
        datatype="sparse_model",
        filenames=("sfm_data.json",),
    ),
)

__all__ = ["RECONSTRUCTION_CODECS"]
