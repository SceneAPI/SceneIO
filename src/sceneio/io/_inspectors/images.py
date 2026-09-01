"""Metadata-only inspection for raster-image formats."""

from __future__ import annotations

import binascii
import re
import struct
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from sceneio import _core
from sceneio.io._inspectors.common import (
    _HEADER_LIMIT,
    _compiled_buffer_inspect,
    _exact,
    _image,
    _unsigned_decimal,
)
from sceneio.io._inspectors.model import Inspection


def _binary_tokens(
    stream: BinaryIO,
    *,
    allow_comments: bool = True,
    extended_whitespace: bool = False,
) -> Iterator[bytes]:
    token = bytearray()
    comment = False
    whitespace = b" \t\r\n\v\f" if extended_whitespace else b" \t\r\n"
    while chunk := stream.read(65536):
        for value in chunk:
            if allow_comments and comment:
                if value in (10, 13):
                    comment = False
                continue
            if allow_comments and value == 35:  # Netpbm comments may follow a number
                if token:
                    yield bytes(token)
                    token.clear()
                comment = True
            elif value in whitespace:
                if token:
                    yield bytes(token)
                    token.clear()
            else:
                token.append(value)
                if len(token) > _HEADER_LIMIT:
                    raise ValueError("metadata token exceeds 1 MiB")
    if token:
        yield bytes(token)


def _next_tokens(
    path: Path,
    count: int,
    *,
    allow_comments: bool = True,
    extended_whitespace: bool = False,
) -> list[bytes]:
    with path.open("rb") as stream:
        tokens = _binary_tokens(
            stream,
            allow_comments=allow_comments,
            extended_whitespace=extended_whitespace,
        )
        result = []
        for _ in range(count):
            try:
                result.append(next(tokens))
            except StopIteration:
                raise ValueError("truncated header") from None
        return result


def inspect_netpbm(path: Path, payload_kind: str) -> Inspection:
    magic, width_raw, height_raw, maxval_raw = _next_tokens(path, 4, extended_whitespace=True)
    if magic not in {b"P2", b"P3", b"P5", b"P6"}:
        raise ValueError("netpbm: bad magic")
    width = _unsigned_decimal(width_raw, "netpbm width")
    height = _unsigned_decimal(height_raw, "netpbm height")
    maxval = _unsigned_decimal(maxval_raw, "netpbm maxval")
    if width < 1 or height < 1 or not 1 <= maxval <= 65535:
        raise ValueError("netpbm: invalid dimensions or maxval")
    channels = 1 if magic in {b"P2", b"P5"} else 3
    return _image(
        "netpbm",
        payload_kind,
        path.stat().st_size,
        height,
        width,
        channels,
        "uint8" if maxval <= 255 else "uint16",
        ascii=magic in {b"P2", b"P3"},
        maxval=maxval,
    )


def inspect_png(path: Path, payload_kind: str) -> Inspection:
    file_size = path.stat().st_size
    with path.open("rb") as stream:
        if _exact(stream, 8, "PNG signature") != b"\x89PNG\r\n\x1a\n":
            raise ValueError("png: bad signature")
        length, kind = struct.unpack(">I4s", _exact(stream, 8, "PNG IHDR chunk"))
        if length != 13 or kind != b"IHDR":
            raise ValueError("png: missing IHDR")
        ihdr = _exact(stream, 13, "PNG IHDR")
        width, height, bitdepth, color_type, compression, filtering, interlace = struct.unpack(
            ">IIBBBBB", ihdr
        )
        ihdr_crc = struct.unpack(">I", _exact(stream, 4, "PNG IHDR CRC"))[0]
        if binascii.crc32(b"IHDR" + ihdr) != ihdr_crc:
            raise ValueError("png: invalid IHDR CRC")
        if compression != 0 or filtering != 0 or interlace not in {0, 1}:
            raise ValueError("png: unsupported IHDR")
        if color_type == 3 and bitdepth not in {1, 2, 4, 8}:
            raise ValueError("png: unsupported palette bit depth")
        palette_alpha = False
        has_trns = False
        palette_entries = None
        saw_idat = False
        while True:
            length_raw = stream.read(4)
            if not length_raw:
                break
            length = struct.unpack(">I", length_raw)[0]
            kind = _exact(stream, 4, "PNG chunk type")
            if length > file_size - stream.tell() - 4:
                raise ValueError("png: chunk runs past end of file")
            metadata_payload = None
            if kind == b"PLTE":
                if palette_entries is not None or length == 0 or length > 768 or length % 3:
                    raise ValueError("png: invalid PLTE chunk")
                palette_entries = length // 3
                if color_type == 3 and palette_entries > 2**bitdepth:
                    raise ValueError("png: palette has too many entries")
                metadata_payload = _exact(stream, length, "PNG PLTE")
            elif kind == b"tRNS":
                if has_trns:
                    raise ValueError("png: duplicate tRNS chunk")
                has_trns = True
                if color_type == 3:
                    if palette_entries is None or length > palette_entries:
                        raise ValueError("png: invalid palette tRNS chunk")
                    metadata_payload = _exact(stream, length, "PNG tRNS")
                    palette_alpha = any(value != 255 for value in metadata_payload)
                else:
                    raise ValueError("png: non-palette tRNS is unsupported")
            elif kind == b"IEND":
                stream.seek(length, 1)
            elif kind != b"IDAT" and not kind[0] & 0x20:
                raise ValueError(f"png: unsupported critical chunk {kind!r}")
            else:
                stream.seek(length, 1)
            chunk_crc = struct.unpack(">I", _exact(stream, 4, "PNG chunk CRC"))[0]
            if (
                metadata_payload is not None
                and binascii.crc32(kind + metadata_payload) != chunk_crc
            ):
                raise ValueError(f"png: invalid {kind.decode()} CRC")
            if kind == b"IDAT":
                saw_idat = True
                break
            if kind == b"IEND":
                break
        if not saw_idat:
            raise ValueError("png: missing IDAT")
        if color_type == 3 and palette_entries is None:
            raise ValueError("png: palette image is missing PLTE")
    if color_type == 0:
        if bitdepth not in {8, 16} or has_trns:
            raise ValueError("png: unsupported grayscale mode")
        channels = 1
    elif color_type == 2:
        if bitdepth not in {8, 16} or has_trns:
            raise ValueError("png: unsupported RGB mode")
        channels = 3
    elif color_type == 3:
        channels = 4 if palette_alpha else 3
        bitdepth = 8
    elif color_type == 6:
        if bitdepth not in {8, 16} or has_trns:
            raise ValueError("png: unsupported RGBA bit depth")
        channels = 4
    else:
        raise ValueError("png: unsupported color type")
    return _image(
        "png",
        payload_kind,
        file_size,
        height,
        width,
        channels,
        "uint16" if bitdepth == 16 else "uint8",
        interlaced=bool(interlace),
    )


_JPEG_SOF = {0xC0, 0xC1, 0xC2}
_JPEG_ALL_SOF = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}
_JPEG_XMP_IDENTIFIER = b"http://ns.adobe.com/xap/1.0/\0"


def _jpeg_xmp_value(xml: bytes, key: bytes) -> bytes | None:
    attribute = re.search(
        re.escape(key) + rb"\s*=\s*(['\"])(.*?)\1",
        xml,
        re.DOTALL,
    )
    if attribute is not None:
        return attribute.group(2).strip()
    element = re.search(
        rb"<\s*" + re.escape(key) + rb"\s*>(.*?)</\s*" + re.escape(key) + rb"\s*>",
        xml,
        re.DOTALL,
    )
    return None if element is None else element.group(1).strip()


def _jpeg_xmp_uint(xml: bytes, key: bytes, *, positive: bool) -> int | None:
    value = _jpeg_xmp_value(xml, key)
    if value is None:
        return None
    if not value.isdigit() or (positive and int(value) == 0):
        raise ValueError(f"jpeg: malformed GPano XMP integer {key.decode('ascii')}")
    return int(value)


def _jpeg_gpano(body: bytes) -> dict[str, int] | None:
    if not body.startswith(_JPEG_XMP_IDENTIFIER):
        return None
    xml = body[len(_JPEG_XMP_IDENTIFIER) :]
    projection = _jpeg_xmp_value(xml, b"GPano:ProjectionType")
    if projection is None:
        return None
    if projection != b"equirectangular":
        raise ValueError(
            f"jpeg: unsupported GPano ProjectionType {projection.decode('ascii', 'replace')!r}"
        )
    fields = {
        "projection_canvas_width": _jpeg_xmp_uint(xml, b"GPano:FullPanoWidthPixels", positive=True),
        "projection_canvas_height": _jpeg_xmp_uint(
            xml, b"GPano:FullPanoHeightPixels", positive=True
        ),
        "cropped_width": _jpeg_xmp_uint(xml, b"GPano:CroppedAreaImageWidthPixels", positive=True),
        "cropped_height": _jpeg_xmp_uint(xml, b"GPano:CroppedAreaImageHeightPixels", positive=True),
        "projection_crop_left": _jpeg_xmp_uint(xml, b"GPano:CroppedAreaLeftPixels", positive=False),
        "projection_crop_top": _jpeg_xmp_uint(xml, b"GPano:CroppedAreaTopPixels", positive=False),
    }
    return {key: value for key, value in fields.items() if value is not None}


def _validated_gpano_metadata(
    gpano: dict[str, int] | None,
    *,
    width: int,
    height: int,
) -> dict[str, int | str | bool]:
    if gpano is None:
        return {}
    if gpano.get("cropped_width", width) != width or gpano.get("cropped_height", height) != height:
        raise ValueError("jpeg: GPano cropped dimensions disagree with JPEG dimensions")
    canvas_width = gpano.get("projection_canvas_width", width)
    canvas_height = gpano.get("projection_canvas_height", height)
    left = gpano.get("projection_crop_left", 0)
    top = gpano.get("projection_crop_top", 0)
    if (
        left > canvas_width
        or width > canvas_width - left
        or top > canvas_height
        or height > canvas_height - top
    ):
        raise ValueError("jpeg: raster crop exceeds the equirectangular canvas")
    return {
        "projection": "equirectangular",
        "projection_canvas_width": canvas_width,
        "projection_canvas_height": canvas_height,
        "projection_crop_left": left,
        "projection_crop_top": top,
        "is_full_sphere": (
            left == 0 and top == 0 and canvas_width == width and canvas_height == height
        ),
    }


def inspect_jpeg(path: Path, payload_kind: str) -> Inspection:
    file_size = path.stat().st_size
    with path.open("rb") as stream:
        if _exact(stream, 2, "JPEG SOI") != b"\xff\xd8":
            raise ValueError("jpeg: bad signature")
        image_info = None
        gpano = None
        while True:
            value = _exact(stream, 1, "JPEG marker")[0]
            while value != 0xFF:
                value = _exact(stream, 1, "JPEG marker")[0]
            while value == 0xFF:
                value = _exact(stream, 1, "JPEG marker")[0]
            marker = value
            if marker == 0xD9:
                raise ValueError("jpeg: reached EOI before a scan")
            if marker in {0xD8, 0x01} or 0xD0 <= marker <= 0xD7:
                continue
            length = struct.unpack(">H", _exact(stream, 2, "JPEG segment length"))[0]
            if length < 2:
                raise ValueError("jpeg: invalid segment length")
            if marker in _JPEG_SOF:
                if image_info is not None:
                    raise ValueError("jpeg: duplicate SOF marker")
                body = _exact(stream, length - 2, "JPEG SOF")
                if len(body) < 6:
                    raise ValueError("jpeg: truncated SOF")
                precision, height, width, components = struct.unpack(">BHHB", body[:6])
                if precision != 8 or components not in {1, 3, 4}:
                    raise ValueError("jpeg: unsupported precision or component count")
                if len(body) != 6 + 3 * components:
                    raise ValueError("jpeg: SOF length does not match component count")
                channels = 1 if components == 1 else 3
                image_info = (
                    height,
                    width,
                    channels,
                    precision,
                    marker == 0xC2,
                )
                continue
            if marker in _JPEG_ALL_SOF:
                raise ValueError(f"jpeg: unsupported SOF marker 0x{marker:02x}")
            if marker == 0xE1:
                candidate = _jpeg_gpano(_exact(stream, length - 2, "JPEG APP1"))
                if candidate is not None:
                    if gpano is not None:
                        raise ValueError("jpeg: duplicate GPano projection metadata")
                    gpano = candidate
                continue
            stream.seek(length - 2, 1)
            if marker == 0xDA:
                if stream.tell() > file_size:
                    raise ValueError("jpeg: SOS segment runs past end of file")
                if image_info is None:
                    raise ValueError("jpeg: scan appears before SOF")
                height, width, channels, precision, progressive = image_info
                return _image(
                    "jpeg",
                    payload_kind,
                    file_size,
                    height,
                    width,
                    channels,
                    "uint8",
                    precision=precision,
                    progressive=progressive,
                    **_validated_gpano_metadata(
                        gpano,
                        width=width,
                        height=height,
                    ),
                )


def inspect_bmp(path: Path, payload_kind: str) -> Inspection:
    (
        height,
        width,
        channels,
        bits_per_pixel,
        compression,
        palette,
        top_down,
    ) = _compiled_buffer_inspect(path, _core._inspect_bmp)
    return _image(
        "bmp",
        payload_kind,
        path.stat().st_size,
        height,
        width,
        channels,
        "uint8",
        bits_per_pixel=bits_per_pixel,
        compression={0: "BI_RGB", 3: "BI_BITFIELDS"}[compression],
        palette=palette,
        top_down=top_down,
    )


def inspect_tga(path: Path, payload_kind: str) -> Inspection:
    (
        height,
        width,
        channels,
        bits_per_pixel,
        rle,
        palette,
        top_origin,
    ) = _compiled_buffer_inspect(path, _core._inspect_tga)
    return _image(
        "tga",
        payload_kind,
        path.stat().st_size,
        height,
        width,
        channels,
        "uint8",
        bits_per_pixel=bits_per_pixel,
        rle=rle,
        palette=palette,
        origin="top_left" if top_origin else "bottom_left",
    )


_HDR_RESOLUTION = re.compile(rb"^-Y\s+(\d+)\s+\+X\s+(\d+)\s*$")


def inspect_hdr(path: Path, payload_kind: str) -> Inspection:
    with path.open("rb") as stream:
        signature = stream.readline(_HEADER_LIMIT + 1).rstrip(b"\r\n")
        if signature not in {b"#?RADIANCE", b"#?RGBE"}:
            raise ValueError("hdr: bad signature")
        format_seen = False
        while line := stream.readline(_HEADER_LIMIT + 1):
            if len(line) > _HEADER_LIMIT:
                raise ValueError("hdr: metadata line exceeds 1 MiB")
            stripped = line.strip()
            if not stripped:
                break
            if stripped.startswith(b"FORMAT="):
                format_seen |= stripped == b"FORMAT=32-bit_rle_rgbe"
        resolution = stream.readline(_HEADER_LIMIT + 1)
        if len(resolution) > _HEADER_LIMIT:
            raise ValueError("hdr: resolution line exceeds 1 MiB")
        match = _HDR_RESOLUTION.match(resolution.strip())
        if not match:
            raise ValueError("hdr: missing or unsupported resolution line")
        if not format_seen:
            raise ValueError("hdr: unsupported or missing FORMAT")
        height, width = (int(value) for value in match.groups())
        return _image(
            "hdr",
            payload_kind,
            path.stat().st_size,
            height,
            width,
            3,
            "float32",
        )


def _cstr(stream: BinaryIO, what: str, limit: int = 4096) -> bytes:
    result = bytearray()
    while len(result) <= limit:
        value = stream.read(1)
        if not value:
            raise ValueError(f"truncated {what}")
        if value == b"\0":
            return bytes(result)
        result += value
    raise ValueError(f"{what} is too long")


def inspect_exr(path: Path, payload_kind: str) -> Inspection:
    with path.open("rb") as stream:
        stream.seek(0, 2)
        file_size = stream.tell()
        stream.seek(0)
        if _exact(stream, 4, "EXR magic") != b"\x76\x2f\x31\x01":
            raise ValueError("exr: bad signature")
        version = struct.unpack("<I", _exact(stream, 4, "EXR version"))[0]
        if (version & 0xFF) != 2:
            raise ValueError("exr: unsupported version")
        if version & (0x200 | 0x800 | 0x1000):
            raise ValueError("exr: tiled, deep, and multipart images are unsupported")
        data_window = None
        channel_names = []
        channel_name_encodings = []
        channel_types = []
        channels_seen = False
        while name := _cstr(stream, "EXR attribute name"):
            attr_type = _cstr(stream, "EXR attribute type")
            attr_size = struct.unpack("<I", _exact(stream, 4, "EXR attribute size"))[0]
            if name == b"dataWindow" and attr_type == b"box2i" and attr_size == 16:
                value = _exact(stream, attr_size, "EXR dataWindow attribute")
                data_window = struct.unpack("<4i", value)
            elif name == b"channels" and attr_type == b"chlist":
                if channels_seen:
                    raise ValueError("exr: duplicate channels attribute")
                channels_seen = True
                if attr_size > _HEADER_LIMIT:
                    raise ValueError("exr: channel list exceeds 1 MiB")
                value = _exact(stream, attr_size, "EXR channels attribute")
                offset = 0
                while offset < len(value) and value[offset] != 0:
                    end = value.find(b"\0", offset)
                    if end < 0 or end + 17 > len(value):
                        raise ValueError("exr: malformed channel list")
                    raw_name = value[offset:end]
                    try:
                        channel_name = raw_name.decode("utf-8")
                    except UnicodeDecodeError:
                        channel_name = raw_name.decode("latin1")
                        channel_name_encoding = "latin1"
                    else:
                        channel_name_encoding = "utf8"
                    channel_names.append(channel_name)
                    channel_name_encodings.append(channel_name_encoding)
                    channel_types.append(struct.unpack_from("<i", value, end + 1)[0])
                    if len(channel_names) > 4:
                        raise ValueError("exr: unsupported channel set")
                    offset = end + 17
                if offset >= len(value) or value[offset] != 0 or offset + 1 != len(value):
                    raise ValueError("exr: malformed channel list terminator")
            else:
                remaining = file_size - stream.tell()
                if attr_size > remaining:
                    raise ValueError(f"truncated EXR {name!r} attribute")
                stream.seek(attr_size, 1)
        if data_window is None or not channel_names:
            raise ValueError("exr: missing dataWindow or channels")
    min_x, min_y, max_x, max_y = data_window
    width, height = max_x - min_x + 1, max_y - min_y + 1
    if any(pixel_type not in {1, 2} for pixel_type in channel_types):
        raise ValueError("exr: only HALF and FLOAT channels are supported")
    names = set(channel_names)
    if len(channel_names) == 1:
        channels = 1
    elif len(channel_names) == 3 and names == {"R", "G", "B"}:
        channels = 3
    elif len(channel_names) == 4 and names == {"R", "G", "B", "A"}:
        channels = 4
    else:
        raise ValueError("exr: unsupported channel set")
    return _image(
        "exr",
        payload_kind,
        file_size,
        height,
        width,
        channels,
        "float32",
        channel_names=tuple(channel_names),
        channel_name_encodings=tuple(channel_name_encodings),
        channel_dtypes=tuple(
            "float16" if pixel_type == 1 else "float32" for pixel_type in channel_types
        ),
    )


def inspect_webp(path: Path, payload_kind: str) -> Inspection:
    file_size = path.stat().st_size
    with path.open("rb") as stream:
        header = _exact(stream, 12, "WebP RIFF header")
        if header[:4] != b"RIFF" or header[8:] != b"WEBP":
            raise ValueError("webp: bad RIFF/WEBP signature")
        riff_size = struct.unpack_from("<I", header, 4)[0] + 8
        if riff_size < 12 or riff_size > file_size:
            raise ValueError("webp: truncated RIFF")
        alpha_chunk = False
        canvas = None
        bitstream = None
        while stream.tell() < riff_size:
            if riff_size - stream.tell() < 8:
                raise ValueError("webp: truncated chunk header")
            kind, length = struct.unpack("<4sI", _exact(stream, 8, "WebP chunk header"))
            padded = length + (length & 1)
            if padded > riff_size - stream.tell():
                raise ValueError("webp: chunk runs past RIFF boundary")
            prefix = _exact(stream, min(length, 16), f"WebP {kind!r} chunk")
            if length > len(prefix):
                stream.seek(length - len(prefix), 1)
            if length & 1:
                stream.seek(1, 1)
            if kind == b"ALPH":
                alpha_chunk = True
                continue
            if kind == b"VP8X":
                if len(prefix) < 10:
                    raise ValueError("webp: truncated VP8X")
                flags = prefix[0]
                if flags & 0x02:
                    raise ValueError("webp: animated WebP is unsupported")
                width = 1 + int.from_bytes(prefix[4:7], "little")
                height = 1 + int.from_bytes(prefix[7:10], "little")
                if canvas is None:
                    canvas = (height, width)
                continue
            if kind == b"VP8L":
                if len(prefix) < 5 or prefix[0] != 0x2F:
                    raise ValueError("webp: malformed VP8L header")
                if prefix[4] & 0xE0:
                    raise ValueError("webp: unsupported VP8L version")
                width = 1 + prefix[1] + ((prefix[2] & 0x3F) << 8)
                height = 1 + (prefix[2] >> 6) + (prefix[3] << 2) + ((prefix[4] & 0xF) << 10)
                if bitstream is None:
                    bitstream = (height, width, bool(prefix[4] & 0x10))
                continue
            if kind == b"VP8 ":
                if len(prefix) < 10 or prefix[3:6] != b"\x9d\x01\x2a":
                    raise ValueError("webp: malformed VP8 header")
                width = int.from_bytes(prefix[6:8], "little") & 0x3FFF
                height = int.from_bytes(prefix[8:10], "little") & 0x3FFF
                if bitstream is None:
                    bitstream = (height, width, alpha_chunk)
        if bitstream is None:
            raise ValueError("webp: missing image bitstream")
        height, width, bitstream_alpha = bitstream
        if canvas is not None:
            if canvas != (height, width):
                raise ValueError("webp: VP8X canvas does not match bitstream")
            height, width = canvas
        return _image(
            "webp",
            payload_kind,
            file_size,
            height,
            width,
            4 if bitstream_alpha else 3,
            "uint8",
        )
