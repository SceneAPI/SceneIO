"""Built-in dense-MVS codec definitions."""

from __future__ import annotations

from pathlib import Path

from sceneio import _core
from sceneio.io._inspectors.dense import (
    inspect_colmap_fused_visibility,
    inspect_colmap_mvs_consistency,
    inspect_colmap_mvs_depth,
    inspect_colmap_mvs_normal,
)
from sceneio.io._registry.adapters import (
    _file_sink_writer,
    _mmap_reader,
    _mmap_selector_reader,
)
from sceneio.io._registry.model import Codec


def _inspector(function, payload_kind: str):
    def inspect(path: str):
        return function(Path(path), payload_kind)

    return inspect


DENSE_CODECS: tuple[Codec, ...] = (
    Codec(
        "colmap_mvs_depth",
        (),
        _mmap_reader(_core.read_colmap_mvs_depth),
        _file_sink_writer(_core.write_colmap_mvs_depth),
        record=_core.DepthMap,
        payload_kind="depth_map",
        inspect=_inspector(inspect_colmap_mvs_depth, "depth_map"),
        read_window=_mmap_selector_reader(
            _core.read_colmap_mvs_depth_window
        ),
        supported_features=(
            "scalar_float32",
            "little_endian",
            "nonpositive_invalid",
            "pixel_windows",
            "camera_z",
        ),
        unsupported_features=("confidence", "embedded_scale"),
    ),
    Codec(
        "colmap_mvs_normal",
        (),
        _mmap_reader(_core.read_colmap_mvs_normal),
        _file_sink_writer(_core.write_colmap_mvs_normal),
        record=_core.NormalMap,
        payload_kind="normal_map",
        inspect=_inspector(inspect_colmap_mvs_normal, "normal_map"),
        read_window=_mmap_selector_reader(
            _core.read_colmap_mvs_normal_window
        ),
        supported_features=(
            "planar_float32",
            "little_endian",
            "camera_xyz",
            "pixel_windows",
        ),
    ),
    Codec(
        "colmap_mvs_consistency",
        (),
        _mmap_reader(_core.read_colmap_mvs_consistency),
        _file_sink_writer(_core.write_colmap_mvs_consistency),
        record=_core.ConsistencyGraph,
        payload_kind="consistency_graph",
        inspect=_inspector(
            inspect_colmap_mvs_consistency, "consistency_graph"
        ),
        supported_features=(
            "ordered_pixel_entries",
            "zero_count_entries",
            "mvs_sequential_image_indices",
        ),
    ),
    Codec(
        "colmap_fused_visibility",
        (),
        _mmap_reader(_core.read_colmap_fused_visibility),
        _file_sink_writer(_core.write_colmap_fused_visibility),
        record=_core.PointVisibility,
        payload_kind="point_visibility",
        filenames=("fused.ply.vis",),
        inspect=_inspector(
            inspect_colmap_fused_visibility, "point_visibility"
        ),
        supported_features=(
            "csr",
            "zero_visibility_points",
            "mvs_sequential_image_indices",
        ),
    ),
)
