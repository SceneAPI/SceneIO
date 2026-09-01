"""Built-in image-sequence codec definitions."""

from __future__ import annotations

from functools import partial

import sceneio.io._image_sequence as _image_sequence_adapter
import sceneio.io._rtmv as _rtmv_adapter
from sceneio import _core
from sceneio.io._avif import (
    inspect_animated_avif,
    read_animated_avif,
    read_animated_avif_frames,
    write_animated_avif,
)
from sceneio.io._frame_access import ImageFrameAccess
from sceneio.io._registry.adapters import (
    _file_sink_writer,
    _mmap_reader,
    _mmap_selector_reader,
)
from sceneio.io._registry.model import Codec

_WEBM_WRITERS = {
    "vp8-keyframe": _core.write_webm,
    "vp8-temporal": partial(_core.write_webm_temporal, codec="vp8"),
    "vp9-temporal": partial(_core.write_webm_temporal, codec="vp9"),
    "av1-temporal": partial(_core.write_webm_temporal, codec="av1"),
}

_IVF_WRITERS = {
    "vp8": partial(_core.write_ivf, codec="vp8"),
    "vp9": partial(_core.write_ivf, codec="vp9"),
    "av1": partial(_core.write_ivf, codec="av1"),
}


def _write_webm(sequence, path: str, *, profile: str = "vp8-keyframe") -> None:
    try:
        function = _WEBM_WRITERS[profile]
    except KeyError:
        raise ValueError(
            f"WebM writer: unknown profile {profile!r}; expected one of "
            + ", ".join(_WEBM_WRITERS)
        ) from None
    _core._write_to_file(function, sequence, path)


def _write_ivf(sequence, path: str, *, profile: str = "vp9") -> None:
    try:
        function = _IVF_WRITERS[profile]
    except KeyError:
        raise ValueError(
            f"IVF writer: unknown profile {profile!r}; expected one of "
            + ", ".join(_IVF_WRITERS)
        ) from None
    _core._write_to_file(function, sequence, path)


_Y4M_CODEC = Codec(
    "y4m",
    (".y4m",),
    _mmap_reader(_core.read_y4m),
    _file_sink_writer(_core.write_y4m),
    record=_core.ImageSequence,
    payload_kind="image_sequence",
    magic=(b"YUV4MPEG2",),
    read_frames=_mmap_selector_reader(_core.read_y4m_frames),
    supported_features=(
        "uint8",
        "mono",
        "yuv420",
        "yuv422",
        "yuv444",
        "frame_ranges",
        "exact_frame_timing",
    ),
    unsupported_features=(
        "rgb_conversion",
        "high_bit_depth",
        "per_frame_tags",
    ),
)

_WEBM_CODEC = Codec(
    "webm",
    (".webm",),
    _mmap_reader(_core.read_webm),
    _write_webm,
    record=_core.ImageSequence,
    payload_kind="image_sequence",
    magic=(b"\x1a\x45\xdf\xa3",),
    read_frames=_mmap_selector_reader(_core.read_webm_frames),
    lossy=True,
    supported_features=(
        "webm",
        "vp8",
        "vp8_interframes",
        "vp9",
        "av1",
        "high_bit_depth_decode",
        "uint8_normalized_output",
        "uint8",
        "rgb",
        "yuv420",
        "progressive",
        "all_keyframe",
        "temporal_compression",
        "simpleblock_constant_timing",
        "exact_frame_timing",
        "frame_ranges",
        "worker_threads",
        "direct_streaming_write",
        "metadata_only_inspect",
    ),
    unsupported_features=(
        "alpha",
        "audio",
        "subtitles",
        "attachments",
        "chapters",
        "lacing",
        "sub_millisecond_timing",
        "hdr",
        "embedded_metadata",
    ),
)

_IVF_CODEC = Codec(
    "ivf",
    (".ivf",),
    _mmap_reader(_core.read_ivf),
    _write_ivf,
    record=_core.ImageSequence,
    payload_kind="image_sequence",
    magic=(b"DKIF",),
    read_frames=_mmap_selector_reader(_core.read_ivf_frames),
    lossy=True,
    supported_features=(
        "ivf_v0",
        "vp8",
        "vp9",
        "av1",
        "uint8",
        "high_bit_depth_decode",
        "uint8_normalized_output",
        "yuv420",
        "progressive",
        "fixed_rational_timing",
        "frame_ranges",
        "worker_threads",
        "direct_streaming_write",
        "metadata_only_inspect",
    ),
    unsupported_features=(
        "alpha",
        "audio",
        "variable_frame_timing",
        "high_bit_depth_output",
        "embedded_metadata",
    ),
)

_MJPEG_CODEC = Codec(
    "mjpeg",
    (".mjpg", ".mjpeg"),
    _mmap_reader(_core.read_mjpeg),
    _file_sink_writer(_core.write_mjpeg),
    record=_core.ImageSequence,
    payload_kind="image_sequence",
    read_frames=_mmap_selector_reader(_core.read_mjpeg_frames),
    lossy=True,
    supported_features=(
        "raw_concatenated_jpeg",
        "uint8",
        "grayscale",
        "rgb",
        "frame_ranges",
        "direct_streaming_write",
        "metadata_only_inspect",
    ),
    unsupported_features=(
        "alpha",
        "audio",
        "frame_timing",
        "high_bit_depth",
        "embedded_metadata",
    ),
)

_MP4_CODEC = Codec(
    "mp4",
    (".mp4", ".m4v", ".mov"),
    _mmap_reader(_core.read_mp4),
    None,
    record=_core.ImageSequence,
    payload_kind="image_sequence",
    read_frames=_mmap_selector_reader(_core.read_mp4_frames),
    streams_write=False,
    lossy=True,
    supported_features=(
        "iso_bmff",
        "classic_mp4",
        "av1",
        "uint8",
        "source_bit_depth_8_10_12",
        "uint8_normalized_output",
        "monochrome",
        "yuv420",
        "yuv422",
        "yuv444",
        "progressive",
        "variable_frame_timing",
        "composition_offsets",
        "edit_lists",
        "pixel_aspect",
        "frame_ranges",
        "metadata_only_inspect",
    ),
    unsupported_features=(
        "write",
        "fragmented_mp4",
        "alpha",
        "audio",
        "subtitles",
        "high_bit_depth_output",
        "hdr_transfer",
    ),
)

_THEORA_CODEC = Codec(
    "theora",
    (".ogv", ".ogg"),
    _mmap_reader(_core.read_theora),
    _file_sink_writer(_core.write_theora),
    record=_core.ImageSequence,
    payload_kind="image_sequence",
    magic=(b"OggS",),
    read_frames=_mmap_selector_reader(_core.read_theora_frames),
    lossy=True,
    supported_features=(
        "ogg",
        "theora_1_2",
        "uint8",
        "yuv420",
        "progressive",
        "fixed_rational_timing",
        "pixel_aspect",
        "frame_ranges",
        "direct_streaming_write",
        "metadata_only_inspect",
    ),
    unsupported_features=(
        "rgb_conversion",
        "monochrome",
        "yuv422",
        "yuv444",
        "high_bit_depth",
        "tagged_color_space",
        "user_comments",
        "multiple_logical_streams",
        "audio",
        "subtitles",
        "chapters",
        "interlaced_video",
    ),
)

_ANIMATED_WEBP_CODEC = Codec(
    "animated_webp",
    (".webp",),
    _mmap_reader(_core.read_animated_webp),
    _file_sink_writer(_core.write_animated_webp),
    record=_core.ImageSequence,
    payload_kind="image_sequence",
    lossy=True,
    supported_features=(
        "lossless",
        "lossy",
        "rgb",
        "rgba",
        "composited_frames",
        "exact_frame_timing",
        "loop_count",
        "background_rgba",
    ),
    unsupported_features=(
        "sub_millisecond_timing",
        "zero_duration_frames",
        "raw_frame_rectangles",
        "icc",
        "exif",
        "xmp",
    ),
)

_APNG_CODEC = Codec(
    "apng",
    (".png", ".apng"),
    _mmap_reader(_core.read_apng),
    _file_sink_writer(_core.write_apng),
    record=_core.ImageSequence,
    payload_kind="image_sequence",
    supported_features=(
        "uint8",
        "rgb",
        "rgba",
        "composited_frames",
        "exact_frame_timing",
        "loop_count",
        "blend_source",
        "blend_over",
        "dispose_none",
        "dispose_background",
        "dispose_previous",
    ),
    unsupported_features=(
        "separate_default_image",
        "grayscale",
        "palette",
        "high_bit_depth",
        "nonintegral_nanosecond_timing",
        "raw_frame_rectangles",
        "icc",
        "exif",
        "xmp",
    ),
)

_ANIMATED_AVIF_CODEC = Codec(
    "animated_avif",
    (".avif", ".avifs"),
    read_animated_avif,
    write_animated_avif,
    record=_core.ImageSequence,
    payload_kind="image_sequence",
    inspect=inspect_animated_avif,
    read_frames=read_animated_avif_frames,
    streams_write=False,
    requires_features=("PIL",),
    lossy=True,
    supported_features=(
        "avif_1_2",
        "uint8",
        "grayscale",
        "rgb",
        "rgba",
        "straight_alpha",
        "exact_frame_timing",
        "frame_ranges",
        "libavif",
        "libaom_encode",
        "dav1d_decode",
        "worker_threads",
        "metadata_only_inspect",
    ),
    unsupported_features=(
        "sub_millisecond_write_timing",
        "loop_count",
        "background_rgba",
        "audio",
        "subtitles",
        "high_bit_depth",
        "hdr",
        "gain_maps",
        "embedded_icc",
        "embedded_exif",
        "embedded_xmp",
        "non_identity_orientation",
        "direct_streaming_write",
    ),
)


def build_sequence_codecs(
    frame_access: ImageFrameAccess,
) -> tuple[Codec, ...]:
    """Return sequence codecs bound to one live image-frame access object."""

    return (
        _Y4M_CODEC,
        _WEBM_CODEC,
        _IVF_CODEC,
        _MJPEG_CODEC,
        _MP4_CODEC,
        _THEORA_CODEC,
        _ANIMATED_WEBP_CODEC,
        _APNG_CODEC,
        _ANIMATED_AVIF_CODEC,
        Codec(
            "rtmv",
            (),
            partial(_rtmv_adapter.read_rtmv_directory, frame_access),
            None,
            record=_rtmv_adapter.RtmvDataset,
            payload_kind="rtmv_dataset",
            is_directory=True,
            dir_marker="00000.json",
            streams_write=False,
            inspect=partial(
                _rtmv_adapter.inspect_rtmv_directory,
                frame_access,
            ),
            read_frames=partial(
                _rtmv_adapter.read_rtmv_directory_frames,
                frame_access,
            ),
            supported_features=(
                "rtmv_camera_data",
                "camera_to_world",
                "per_view_pinhole_intrinsics",
                "lazy_rgb_exr",
                "lazy_depth_exr",
                "optional_lazy_segmentation_exr",
                "lazy_object_metadata",
                "frame_ranges",
                "metadata_only_inspect",
            ),
            unsupported_features=(
                "pixel_decode",
                "object_annotation_projection",
                "directory_write",
            ),
        ),
        Codec(
            "image_sequence",
            (),
            partial(
                _image_sequence_adapter.read_image_sequence_directory,
                frame_access,
            ),
            partial(
                _image_sequence_adapter.write_image_sequence_directory,
                frame_access,
            ),
            record=_core.ImageSequence,
            payload_kind="image_sequence",
            is_directory=True,
            dir_marker="sceneio_sequence.json",
            inspect=partial(
                _image_sequence_adapter.inspect_image_sequence_directory,
                frame_access,
            ),
            read_frames=partial(
                _image_sequence_adapter.read_image_sequence_directory_frames,
                frame_access,
            ),
            supported_features=(
                "lazy_encoded_frames",
                "natural_order",
                "manifest_timing",
                "frame_ranges",
                "semantic_single_image_frames",
                "manifest_v2_frame_contract",
                "equirectangular_manifest",
                "typed_packed_frame_encoding",
            ),
            unsupported_features=(
                "recursive_directories",
                "heterogeneous_frames",
                "pixel_decode",
            ),
        ),
    )
