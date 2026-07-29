"""Built-in image-sequence codec definitions."""

from __future__ import annotations

from functools import partial

import sceneio.io._image_sequence as _image_sequence_adapter
from sceneio import _core
from sceneio.io._frame_access import ImageFrameAccess
from sceneio.io._registry.adapters import (
    _file_sink_writer,
    _mmap_reader,
    _mmap_selector_reader,
)
from sceneio.io._registry.model import Codec

_Y4M_CODEC = Codec(
    "y4m",
    (".y4m",),
    _mmap_reader(_core.read_y4m),
    _file_sink_writer(_core.write_y4m),
    record=_core.ImageSequence,
    datatype="image_sequence",
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

_ANIMATED_WEBP_CODEC = Codec(
    "animated_webp",
    (".webp",),
    _mmap_reader(_core.read_animated_webp),
    _file_sink_writer(_core.write_animated_webp),
    record=_core.ImageSequence,
    datatype="image_sequence",
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


def build_sequence_codecs(
    frame_access: ImageFrameAccess,
) -> tuple[Codec, ...]:
    """Return sequence codecs bound to one live image-frame access object."""

    return (
        _Y4M_CODEC,
        _ANIMATED_WEBP_CODEC,
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
            datatype="image_sequence",
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
            ),
            unsupported_features=(
                "recursive_directories",
                "heterogeneous_frames",
                "pixel_decode",
            ),
        ),
    )
