"""Built-in Gaussian-splat codec definitions."""

from __future__ import annotations

from sceneio import _core
from sceneio.io._registry.adapters import (
    _file_sink_writer,
    _mmap_reader,
    _mmap_selector_reader,
)
from sceneio.io._registry.model import Codec


def build_splat_codecs(
    _sog_reader,
    _sog_writer,
    _sog_point_reader,
) -> tuple[Codec, ...]:
    """Build the splat family with registry-owned SOG path adapters."""

    return (
        Codec(
            "gaussian_ply",
            (".ply",),
            _mmap_reader(_core.read_gaussian_ply),
            _file_sink_writer(_core.write_gaussian_ply),
            record=_core.GaussianCloud,
            payload_kind="splat",
            magic=(b"ply",),
            read_points=_mmap_selector_reader(
                _core.read_gaussian_ply_points
            ),
        ),
        Codec(
            "compressed_ply",
            (".compressed.ply",),
            _mmap_reader(_core.read_compressed_ply),
            _file_sink_writer(_core.write_compressed_ply),
            record=_core.GaussianCloud,
            payload_kind="splat",
            magic=(b"ply",),
            read_points=_mmap_selector_reader(
                _core.read_compressed_ply_points
            ),
            lossy=True,
            supported_features=(
                "playcanvas_chunk_256",
                "legacy_direct_color_read",
                "position_11_10_11",
                "scale_11_10_11",
                "largest_three_quaternion",
                "rgba8",
                "sh_degrees_0_3",
                "morton_ordered_write",
            ),
            unsupported_features=(
                "ascii",
                "binary_big_endian",
                "unknown_elements",
                "unknown_properties",
            ),
        ),
        Codec(
            "sog",
            (".sog",),
            _sog_reader,
            _sog_writer,
            record=_core.GaussianCloud,
            payload_kind="splat",
            filenames=("meta.json",),
            is_directory=True,
            dir_marker="meta.json",
            read_points=_sog_point_reader,
            lossy=True,
            container_kind="multi_file",
            supported_features=(
                "playcanvas_v2",
                "bundled_zip",
                "unbundled_directory",
                "lossless_webp_layers",
                "position_16bit_log",
                "largest_three_quaternion",
                "shared_scale_dc_codebooks",
                "sh_degrees_0_3",
                "sh_palette",
                "morton_ordered_write",
            ),
            unsupported_features=(
                "legacy_v1",
                "lossy_webp_layers",
                "streamed_lod",
                "unknown_layers",
            ),
        ),
        Codec(
            "ksplat",
            (".ksplat",),
            _mmap_reader(_core.read_ksplat),
            _file_sink_writer(_core.write_ksplat),
            record=_core.GaussianCloud,
            payload_kind="splat",
            read_points=_mmap_selector_reader(_core.read_ksplat_points),
            lossy=True,
            supported_features=(
                "mkkellogg_v0_1",
                "compression_levels_0_2",
                "float16_scale_rotation",
                "bucketed_position_uint16",
                "rgba8",
                "sh_degrees_0_2",
                "sh_uint8_level_2",
                "multi_section_read",
                "deterministic_single_section_write",
            ),
            unsupported_features=(
                "sh_degree_3",
                "unknown_versions",
                "streamed_lod",
            ),
        ),
        Codec(
            "spz",
            (".spz",),
            _mmap_reader(_core.read_spz),
            _file_sink_writer(_core.write_spz),
            record=_core.GaussianCloud,
            payload_kind="splat",
            magic=(b"\x1f\x8b", b"NGSP"),
            lossy=True,
            supported_features=(
                "v1_read",
                "v2_read",
                "v3_read_write",
                "v4_read_write",
            ),
        ),
        # antimatter15 .splat is headerless, so detection is extension-only.
        # It is the web-viewer sibling of SPZ; both expose the splat payload_kind.
        Codec(
            "splat",
            (".splat",),
            _mmap_reader(_core.read_splat),
            _file_sink_writer(_core.write_splat),
            record=_core.GaussianCloud,
            payload_kind="splat",
            read_points=_mmap_selector_reader(_core.read_splat_points),
            lossy=True,
            supported_features=("rgb8", "opacity8", "scale8", "quaternion8"),
            unsupported_features=("spherical_harmonics",),
        ),
    )
