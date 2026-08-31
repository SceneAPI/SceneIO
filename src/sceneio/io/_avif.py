"""Bounded AVIF still and image-sequence I/O without a video framework.

The repository owns this adapter and delegates AV1 compression to Pillow's
libavif provider.  Decoding passes a read-only mmap directly to the provider;
decoded pixels are copied into SceneIO-owned records before the mapping closes.
Only 8-bit gray, RGB, and straight-alpha RGBA data is admitted.
"""

from __future__ import annotations

import mmap
import os
import tempfile
from contextlib import suppress
from pathlib import Path

import numpy as np

from sceneio import _core
from sceneio.io._inspectors.common import _IMAGE_PIXEL_CAP
from sceneio.io._inspectors.model import ArrayInspection, Inspection

_NANOSECONDS_PER_SECOND = 1_000_000_000
_MILLISECONDS_IN_NS = 1_000_000
_SEQUENCE_SAMPLE_CAP = 1_000_000_000
_METADATA_BYTE_CAP = 16 * 1024 * 1024
_MODES = {"L": 1, "RGB": 3, "RGBA": 4}
_CONTAINER_OFFSETS = {
    b"meta": 4,
    b"moov": 0,
    b"trak": 0,
    b"mdia": 0,
    b"minf": 0,
    b"stbl": 0,
    b"dinf": 0,
    b"edts": 0,
    b"iprp": 0,
    b"ipco": 0,
    b"iref": 4,
    b"grpl": 4,
}
_REFUSED_BOX_TYPES = {
    b"a1lx",  # AV1 layer index
    b"a1op",  # AV1 operating point
    b"altr",  # alternate entity group
    b"amve",  # ambient viewing environment
    b"cclv",  # content color volume
    b"clli",  # content light level
    b"dimg",  # derived-image reference
    b"lsel",  # layer selector
    b"mdcv",  # mastering display color volume
    b"ndwt",  # nominal diffuse white
    b"prem",  # premultiplied-alpha reference
    b"reve",  # reference viewing environment
    b"ster",  # stereo entity group
    b"thmb",  # thumbnail reference
}
_REFUSED_ITEM_TYPES = {b"grid", b"sato", b"tmap"}
_REFUSED_HANDLER_TYPES = {b"clcp", b"sbtl", b"soun", b"subt", b"text"}
_HDR_TRANSFER_CHARACTERISTICS = {16, 18}  # SMPTE ST 2084 (PQ), ARIB STD-B67 (HLG)
_DEPTH_AUX_TYPE = b"urn:mpeg:mpegB:cicp:systems:auxiliary:depth"


def _uint(data, offset: int, size: int) -> int:
    return int.from_bytes(data[offset : offset + size], "big")


def _boxes(data, start: int, end: int):
    """Yield validated ISO-BMFF boxes as (type, payload_start, end)."""

    cursor = start
    while cursor < end:
        if end - cursor < 8:
            raise ValueError("AVIF: truncated ISO-BMFF box header")
        box_size = _uint(data, cursor, 4)
        box_type = bytes(data[cursor + 4 : cursor + 8])
        header_size = 8
        if box_size == 1:
            if end - cursor < 16:
                raise ValueError("AVIF: truncated extended ISO-BMFF box header")
            box_size = _uint(data, cursor + 8, 8)
            header_size = 16
        elif box_size == 0:
            box_size = end - cursor
        if box_size < header_size or box_size > end - cursor:
            raise ValueError("AVIF: invalid ISO-BMFF box extent")
        box_end = cursor + box_size
        yield box_type, cursor + header_size, box_end
        cursor = box_end


def _child_start(data, box_type: bytes, payload_start: int, box_end: int):
    if box_type in _CONTAINER_OFFSETS:
        child_start = payload_start + _CONTAINER_OFFSETS[box_type]
    elif box_type == b"iinf":
        if box_end - payload_start < 6:
            raise ValueError("AVIF: truncated item-information box")
        version = data[payload_start]
        child_start = payload_start + (6 if version == 0 else 8)
    elif box_type == b"stsd":
        child_start = payload_start + 8  # FullBox fields and entry_count.
    elif box_type in {b"av01", b"encv"}:
        child_start = payload_start + 78  # VisualSampleEntry fields.
    else:
        return None
    if child_start > box_end:
        raise ValueError("AVIF: truncated ISO-BMFF container box")
    return child_start


def _walk_boxes(data, start: int, end: int):
    for box_type, payload_start, box_end in _boxes(data, start, end):
        yield box_type, payload_start, box_end
        child_start = _child_start(data, box_type, payload_start, box_end)
        if child_start is not None and child_start < box_end:
            yield from _walk_boxes(data, child_start, box_end)


def _infe_item_type(data, payload_start: int, box_end: int):
    if box_end - payload_start < 4:
        raise ValueError("AVIF: truncated item-info entry")
    version = data[payload_start]
    if version == 2:
        offset = payload_start + 8
    elif version == 3:
        offset = payload_start + 10
    else:
        return None
    if offset + 4 > box_end:
        raise ValueError("AVIF: truncated item-info entry type")
    return bytes(data[offset : offset + 4])


def _validate_container_profile(data) -> None:
    """Refuse AVIF features the Image/ImageSequence models cannot preserve."""

    total_size = len(data)
    metadata_size = 0
    metadata_ranges = []
    brands = set()
    top_cursor = 0
    for box_type, payload_start, box_end in _boxes(data, 0, total_size):
        box_start = top_cursor
        top_cursor = box_end
        if box_type == b"ftyp":
            if box_end - payload_start < 8 or (box_end - payload_start) % 4:
                raise ValueError("AVIF: malformed file-type box")
            brands.add(bytes(data[payload_start : payload_start + 4]))
            for offset in range(payload_start + 8, box_end, 4):
                brands.add(bytes(data[offset : offset + 4]))
        if box_type != b"mdat":
            metadata_size += box_end - box_start
            if metadata_size > _METADATA_BYTE_CAP:
                raise ValueError("AVIF: container metadata exceeds the supported limit")
            metadata_ranges.append((box_start, box_end))
    if not brands.intersection({b"avif", b"avis"}):
        raise ValueError("AVIF: file-type box does not declare an AVIF brand")

    av1_config_count = 0
    for range_start, range_end in metadata_ranges:
        for box_type, payload_start, box_end in _walk_boxes(
            data, range_start, range_end
        ):
            if box_type in _REFUSED_BOX_TYPES:
                name = box_type.decode("ascii", errors="replace")
                raise ValueError(f"AVIF: {name} structures are outside this profile")
            if box_type == b"infe":
                item_type = _infe_item_type(data, payload_start, box_end)
                if item_type in _REFUSED_ITEM_TYPES:
                    name = item_type.decode("ascii", errors="replace")
                    raise ValueError(f"AVIF: {name} image items are outside this profile")
            elif box_type == b"av1C":
                if box_end - payload_start < 4 or data[payload_start] != 0x81:
                    raise ValueError("AVIF: malformed AV1 codec configuration")
                av1_config_count += 1
                if data[payload_start + 2] & 0x60:
                    raise ValueError("AVIF: only 8-bit AV1 samples are supported")
            elif box_type == b"colr":
                if (
                    box_end - payload_start >= 11
                    and bytes(data[payload_start : payload_start + 4]) == b"nclx"
                    and _uint(data, payload_start + 6, 2)
                    in _HDR_TRANSFER_CHARACTERISTICS
                ):
                    raise ValueError("AVIF: HDR transfer functions are outside this profile")
            elif box_type == b"auxC":
                probe_end = min(box_end, payload_start + 256)
                if _DEPTH_AUX_TYPE in bytes(data[payload_start:probe_end]):
                    raise ValueError("AVIF: auxiliary depth images are outside this profile")
            elif box_type == b"hdlr":
                if box_end - payload_start < 12:
                    raise ValueError("AVIF: truncated handler box")
                handler_type = bytes(data[payload_start + 8 : payload_start + 12])
                if handler_type in _REFUSED_HANDLER_TYPES:
                    name = handler_type.decode("ascii", errors="replace")
                    raise ValueError(f"AVIF: {name} tracks are outside this profile")
    if av1_config_count == 0:
        raise ValueError("AVIF: missing AV1 codec configuration")


def _default_max_threads() -> int:
    if hasattr(os, "sched_getaffinity"):
        return max(1, len(os.sched_getaffinity(0)))
    return max(1, os.cpu_count() or 1)


def _require_provider():
    try:
        from PIL import Image as PillowImage
        from PIL import _avif, features
    except (ImportError, ModuleNotFoundError):
        raise RuntimeError(
            "AVIF support requires the optional dependency; "
            "install sceneio[avif]"
        ) from None
    if not features.check_module("avif"):
        raise RuntimeError(
            "the installed Pillow build does not include AVIF support; "
            "install sceneio[avif] from a supported wheel"
        )
    return PillowImage, _avif


def _validate_info(info, *, expect_sequence: bool):
    try:
        (width, height), frame_count, mode, icc, exif, orientation, xmp = info
    except (TypeError, ValueError):
        raise ValueError("AVIF: provider returned malformed image metadata") from None
    width = int(width)
    height = int(height)
    frame_count = int(frame_count)
    channels = _MODES.get(mode)
    if width < 1 or height < 1 or frame_count < 1 or channels is None:
        raise ValueError("AVIF: unsupported dimensions, frame count, or pixel mode")
    if width * height > _IMAGE_PIXEL_CAP:
        raise ValueError("AVIF: image dimensions exceed the supported limit")
    if frame_count * width * height * channels > _SEQUENCE_SAMPLE_CAP:
        raise ValueError("AVIF: decoded sequence exceeds the supported limit")
    if bool(expect_sequence) != (frame_count > 1):
        expected = "an image sequence" if expect_sequence else "a still image"
        raise ValueError(f"AVIF: input is not {expected}")
    if icc:
        raise ValueError("AVIF: embedded ICC profiles are outside this profile")
    if exif:
        raise ValueError("AVIF: embedded EXIF metadata is outside this profile")
    if xmp:
        raise ValueError("AVIF: embedded XMP metadata is outside this profile")
    if int(orientation) != 1:
        raise ValueError("AVIF: non-identity orientation is outside this profile")
    return width, height, frame_count, mode, channels


def _run_decoder(path: str | Path, operation):
    _pillow_image, avif = _require_provider()
    source = Path(path)
    with source.open("rb") as stream:
        if os.fstat(stream.fileno()).st_size == 0:
            raise ValueError("AVIF: empty input")
        mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        view = memoryview(mapped)
        decoder = None
        result = None
        error = None
        try:
            # Pillow 12.3's provider accepts the buffer protocol here. Keeping
            # the mapping and exported view alive through the final frame call
            # makes the zero-copy input lifetime explicit.
            try:
                _validate_container_profile(mapped)
                decoder = avif.AvifDecoder(
                    view,
                    "auto",
                    _default_max_threads(),
                )
                result = operation(decoder)
            except SyntaxError as exc:
                error = (
                    ValueError,
                    (f"AVIF: provider rejected the container: {exc}",),
                )
            except BaseException as exc:
                # An active traceback retains the operation frame and its
                # decoder argument. Detach the traceback and exception chain
                # so the decoder releases its exported Py_buffer before the
                # mmap is closed, while preserving the original exception.
                exc.__traceback__ = None
                exc.__context__ = None
                exc.__cause__ = None
                error = exc
        finally:
            decoder = None
            view.release()
            mapped.close()
        if error is not None:
            raise error from None
        return result


def _frame_shape(height: int, width: int, channels: int) -> tuple[int, ...]:
    return (height, width) if channels == 1 else (height, width, channels)


def _decode_frame(decoder, index: int, shape: tuple[int, ...]):
    try:
        payload, timescale, timestamp, duration = decoder.get_frame(index)
    except (IndexError, RuntimeError, ValueError, OSError) as exc:
        raise ValueError(f"AVIF: could not decode frame {index}: {exc}") from exc
    expected = int(np.prod(shape, dtype=np.int64))
    if len(payload) != expected:
        raise ValueError("AVIF: decoded pixel extent disagrees with metadata")
    timescale = int(timescale)
    timestamp = int(timestamp)
    duration = int(duration)
    if timescale <= 0 or timestamp < 0 or duration <= 0:
        raise ValueError("AVIF: invalid frame timing")
    timestamp_product = timestamp * _NANOSECONDS_PER_SECOND
    duration_product = duration * _NANOSECONDS_PER_SECOND
    if timestamp_product % timescale or duration_product % timescale:
        raise ValueError("AVIF: frame timing is not representable in nanoseconds")
    timestamp_ns = timestamp_product // timescale
    duration_ns = duration_product // timescale
    if timestamp_ns > np.iinfo(np.int64).max or duration_ns > np.iinfo(np.int64).max:
        raise ValueError("AVIF: frame timing exceeds int64 nanoseconds")
    pixels = np.frombuffer(payload, dtype=np.uint8)
    return pixels.reshape(shape), timestamp_ns, duration_ns


def read_avif(path: str | Path):
    """Decode one bounded 8-bit AVIF still into an owned ``Image``."""

    def decode(decoder):
        width, height, _count, mode, channels = _validate_info(
            decoder.get_info(), expect_sequence=False
        )
        pixels, _timestamp, _duration = _decode_frame(
            decoder, 0, _frame_shape(height, width, channels)
        )
        return _core.image(
            pixels,
            color_space="gray" if mode == "L" else "unknown",
            alpha_mode="straight" if mode == "RGBA" else "none",
        )

    return _run_decoder(path, decode)


def _read_animated_avif(path: str | Path, start: int | None, stop: int | None):
    def decode(decoder):
        width, height, frame_count, mode, channels = _validate_info(
            decoder.get_info(), expect_sequence=True
        )
        begin = 0 if start is None else int(start)
        end = frame_count if stop is None else int(stop)
        if begin < 0 or begin >= end or end > frame_count:
            raise ValueError(
                f"AVIF: frame range must satisfy 0 <= start < stop <= {frame_count}"
            )
        one_shape = _frame_shape(height, width, channels)
        output_shape = (end - begin, *one_shape)
        pixels = np.empty(output_shape, dtype=np.uint8)
        timestamps = np.empty(end - begin, dtype=np.int64)
        durations = np.empty(end - begin, dtype=np.int64)
        for output_index, source_index in enumerate(range(begin, end)):
            frame, timestamp_ns, duration_ns = _decode_frame(
                decoder, source_index, one_shape
            )
            pixels[output_index] = frame
            timestamps[output_index] = timestamp_ns
            durations[output_index] = duration_ns
        return _core.image_sequence_packed(
            pixels,
            timestamps,
            durations,
            "gray" if mode == "L" else "unknown",
            "straight" if mode == "RGBA" else "none",
        )

    return _run_decoder(path, decode)


def read_animated_avif(path: str | Path):
    """Decode all frames of one AVIF image sequence."""

    return _read_animated_avif(path, None, None)


def read_animated_avif_frames(path: str | Path, start: int, stop: int):
    """Decode a non-empty half-open AVIF frame range."""

    return _read_animated_avif(path, start, stop)


def _validate_image(value) -> tuple[np.ndarray, str]:
    if not isinstance(value, _core.Image):
        raise TypeError("AVIF still writer: expected an Image")
    pixels = np.asarray(value.pixels)
    if pixels.dtype != np.uint8 or not pixels.flags.c_contiguous:
        raise ValueError("AVIF still writer: pixels must be C-contiguous uint8")
    if value.maxval != 255:
        raise ValueError("AVIF still writer: uint8 pixels require maxval 255")
    if value.channels == 1:
        if value.color_space != "gray" or value.alpha_mode != "none":
            raise ValueError("AVIF still writer: grayscale conventions disagree")
        return pixels, "L"
    if value.color_space != "srgb":
        raise ValueError("AVIF still writer: RGB/RGBA pixels must be sRGB")
    if value.channels == 3 and value.alpha_mode == "none":
        return pixels, "RGB"
    if value.channels == 4 and value.alpha_mode == "straight":
        return pixels, "RGBA"
    raise ValueError("AVIF still writer: only RGB or straight-alpha RGBA is supported")


def _validate_sequence(value):
    if not isinstance(value, _core.ImageSequence):
        raise TypeError("animated AVIF writer: expected an ImageSequence")
    if value.has_acquisition_timing:
        raise ValueError(
            "animated AVIF writer: acquisition timing metadata is not representable"
        )
    if value.storage_mode != "packed" or value.frame_dtype != "uint8":
        raise ValueError("animated AVIF writer: requires packed uint8 frames")
    if value.maxval != 255:
        raise ValueError("animated AVIF writer: uint8 frames require maxval 255")
    if value.num_frames < 2:
        raise ValueError("animated AVIF writer: requires at least two frames")
    if not value.has_timing:
        raise ValueError("animated AVIF writer: exact frame timing is required")
    if value.has_loop_count or value.has_background:
        raise ValueError("animated AVIF writer: loop/background metadata is not representable")
    if value.channels == 1:
        if value.color_space != "gray" or value.alpha_mode != "none":
            raise ValueError("animated AVIF writer: grayscale conventions disagree")
        mode = "L"
    elif value.channels == 3:
        if value.color_space != "srgb" or value.alpha_mode != "none":
            raise ValueError("animated AVIF writer: RGB frames must be sRGB without alpha")
        mode = "RGB"
    elif value.channels == 4:
        if value.color_space != "srgb" or value.alpha_mode != "straight":
            raise ValueError("animated AVIF writer: RGBA frames require straight sRGB alpha")
        mode = "RGBA"
    else:
        raise ValueError("animated AVIF writer: unsupported channel count")
    timestamps = np.asarray(value.timestamps_ns)
    durations = np.asarray(value.durations_ns)
    if timestamps[0] != 0:
        raise ValueError("animated AVIF writer: timestamps must start at zero")
    if np.any(timestamps[1:] != timestamps[:-1] + durations[:-1]):
        raise ValueError("animated AVIF writer: frame timing must be contiguous")
    if np.any(durations % _MILLISECONDS_IN_NS):
        raise ValueError("animated AVIF writer: durations must be whole milliseconds")
    duration_ms = (durations // _MILLISECONDS_IN_NS).tolist()
    return np.asarray(value.pixels), mode, duration_ms


def _atomic_save(destination: str | Path, save) -> None:
    target = Path(destination)
    target.parent.mkdir(parents=False, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        save(temporary)
        os.replace(temporary, target)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def write_avif(
    value,
    path: str | Path,
    *,
    quality: int = 90,
    speed: int = 6,
) -> None:
    """Encode one 8-bit AVIF still through Pillow's optimized libavif build."""

    PillowImage, _avif = _require_provider()
    pixels, mode = _validate_image(value)
    if isinstance(quality, bool) or not isinstance(quality, int) or not 0 <= quality <= 100:
        raise ValueError("AVIF still writer: quality must be an integer in 0..100")
    if isinstance(speed, bool) or not isinstance(speed, int) or not 0 <= speed <= 10:
        raise ValueError("AVIF still writer: speed must be an integer in 0..10")
    image = PillowImage.fromarray(pixels, mode=mode)
    subsampling = "4:0:0" if mode == "L" else "4:4:4"
    _atomic_save(
        path,
        lambda temporary: image.save(
            temporary,
            format="AVIF",
            quality=quality,
            speed=speed,
            subsampling=subsampling,
            range="full",
            autotiling=True,
            alpha_premultiplied=False,
        ),
    )


def write_animated_avif(
    value,
    path: str | Path,
    *,
    quality: int = 90,
    speed: int = 6,
) -> None:
    """Encode one timed 8-bit AVIF image sequence."""

    PillowImage, _avif = _require_provider()
    pixels, mode, durations_ms = _validate_sequence(value)
    if isinstance(quality, bool) or not isinstance(quality, int) or not 0 <= quality <= 100:
        raise ValueError("animated AVIF writer: quality must be an integer in 0..100")
    if isinstance(speed, bool) or not isinstance(speed, int) or not 0 <= speed <= 10:
        raise ValueError("animated AVIF writer: speed must be an integer in 0..10")
    frames = [PillowImage.fromarray(frame, mode=mode) for frame in pixels]
    subsampling = "4:0:0" if mode == "L" else "4:4:4"
    _atomic_save(
        path,
        lambda temporary: frames[0].save(
            temporary,
            format="AVIF",
            save_all=True,
            append_images=frames[1:],
            duration=durations_ms,
            quality=quality,
            speed=speed,
            subsampling=subsampling,
            range="full",
            autotiling=True,
            alpha_premultiplied=False,
        ),
    )


def _inspect(path: str | Path, *, sequence: bool) -> Inspection:
    source = Path(path)

    def inspect_decoder(decoder):
        width, height, frame_count, mode, channels = _validate_info(
            decoder.get_info(), expect_sequence=sequence
        )
        one_shape = _frame_shape(height, width, channels)
        shape = (frame_count, *one_shape) if sequence else one_shape
        metadata = {
            "storage_mode": "packed" if sequence else "interleaved",
            "color_space": "gray" if mode == "L" else "unknown",
            "alpha_mode": "straight" if mode == "RGBA" else "none",
            "provider": "Pillow/libavif",
        }
        return Inspection(
            format="animated_avif" if sequence else "avif",
            payload_kind="image_sequence" if sequence else "image",
            byte_size=source.stat().st_size,
            shape=shape,
            dtype="uint8",
            count=frame_count if sequence else None,
            channels=channels,
            arrays=(ArrayInspection("pixels", shape, "uint8"),),
            metadata=metadata,
        )

    return _run_decoder(source, inspect_decoder)


def inspect_avif(path: str | Path) -> Inspection:
    """Inspect an AVIF still without decoding its pixel payload."""

    return _inspect(path, sequence=False)


def inspect_animated_avif(path: str | Path) -> Inspection:
    """Inspect an AVIF image sequence without decoding its pixel payload."""

    return _inspect(path, sequence=True)


__all__ = [
    "inspect_animated_avif",
    "inspect_avif",
    "read_animated_avif",
    "read_animated_avif_frames",
    "read_avif",
    "write_animated_avif",
    "write_avif",
]
