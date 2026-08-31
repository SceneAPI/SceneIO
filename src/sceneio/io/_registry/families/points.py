"""Built-in point-cloud codec definitions."""

from __future__ import annotations

from sceneio import _core
from sceneio.io._e57 import inspect_e57, read_e57, write_e57
from sceneio.io._registry.adapters import (
    _file_sink_writer,
    _mmap_reader,
    _mmap_selector_reader,
)
from sceneio.io._registry.model import Codec

POINT_CODECS: tuple[Codec, ...] = (
    Codec(
        "ply",
        (".ply",),
        _mmap_reader(_core.read_ply),
        _file_sink_writer(_core.write_ply),
        record=_core.PointCloud,
        payload_kind="point_cloud",
        read_points=_mmap_selector_reader(_core.read_ply_points),
        supported_features=(
            "ascii",
            "binary_little_endian",
            "binary_big_endian",
            "standard_scalar_types_read",
            "normals",
            "rgb8",
            "rgb16",
            "intensity",
        ),
        unsupported_features=(
            "vertex_lists",
            "unknown_vertex_properties",
            "non_vertex_elements",
            "ascii_point_ranges",
        ),
    ),
    Codec(
        "pcd",
        (".pcd",),
        _mmap_reader(_core.read_pcd),
        _file_sink_writer(_core.write_pcd),
        record=_core.PointCloud,
        payload_kind="point_cloud",
        magic=(b"# .PCD",),
        read_points=_mmap_selector_reader(_core.read_pcd_points),
        supported_features=(
            "pcd_0_7",
            "ascii",
            "binary",
            "binary_compressed",
            "organized",
            "viewpoint",
            "standard_scalar_types_read",
            "normals",
            "packed_rgb8",
            "intensity",
        ),
        unsupported_features=(
            "unknown_fields",
            "multi_count_fields",
            "rgb16",
            "ascii_point_ranges",
            "compressed_point_ranges",
        ),
    ),
    Codec(
        "xyz",
        (".xyz",),
        _mmap_reader(_core.read_xyz),
        _file_sink_writer(_core.write_xyz),
        record=_core.PointCloud,
        payload_kind="point_cloud",
        read_points=_mmap_selector_reader(_core.read_xyz_points),
    ),
    Codec(
        "pts",
        (".pts",),
        _mmap_reader(_core.read_pts),
        _file_sink_writer(_core.write_pts),
        record=_core.PointCloud,
        payload_kind="point_cloud",
        read_points=_mmap_selector_reader(_core.read_pts_points),
        supported_features=(
            "count_header",
            "xyz",
            "intensity",
            "rgb8",
        ),
        unsupported_features=("normals", "rgb16", "georef"),
    ),
    # ASPRS LAS (hand-parsed binary, no library) -> PointCloud. The "LASF"
    # signature is unambiguous. Waveform formats retain their descriptor VLRs,
    # raw point fields, and internal packet EVLR in a lossless sidecar.
    Codec(
        "las",
        (".las",),
        _mmap_reader(_core.read_las),
        _file_sink_writer(_core.write_las),
        record=_core.PointCloud,
        payload_kind="point_cloud",
        magic=(b"LASF",),
        read_points=_mmap_selector_reader(_core.read_las_points),
        lossy=True,
        supported_features=(
            "point_formats_0_5",
            "point_formats_6_10",
            "waveform_sidecar",
            "rgb16",
            "georef",
        ),
        unsupported_features=("external_waveform_packets", "laz"),
    ),
    # LASzip-compatible LAZ through pinned LAZperf. The decoded PointCloud
    # model intentionally keeps only coordinates, intensity, and RGB; formats
    # carrying GPS time or NIR therefore advertise a lossy projection.
    Codec(
        "laz",
        (".laz",),
        _mmap_reader(_core.read_laz),
        _file_sink_writer(_core.write_laz),
        record=_core.PointCloud,
        payload_kind="point_cloud",
        read_points=_mmap_selector_reader(_core.read_laz_points),
        lossy=True,
        supported_features=(
            "point_formats_0_3",
            "point_formats_6_8",
            "chunked_point_ranges",
            "rgb16",
            "georef",
        ),
        unsupported_features=(
            "point_formats_4_5",
            "point_formats_9_10",
            "waveform",
            "extra_bytes",
            "vlr_metadata",
        ),
    ),
    Codec(
        "e57",
        (".e57",),
        read_e57,
        write_e57,
        record=_core.ScanSet,
        payload_kind="scan_set",
        magic=(b"ASTM-E57",),
        inspect=inspect_e57,
        requires_features=("pye57",),
        supported_features=(
            "cartesian_float32_exact",
            "rgb8",
            "float32_intensity",
            "invalid_state_rows",
            "scan_pose",
            "metadata_only_inspect",
            "transactional_path_write",
            "multiple_scans",
            "organized_row_column",
            "stored_point_ranges",
        ),
        unsupported_features=(
            "spherical_coordinates",
            "normals",
            "rgb16",
            "images",
            "point_grouping",
            "non_float32_exact_coordinates",
        ),
    ),
)
