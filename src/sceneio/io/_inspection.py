"""Metadata-only inspection for SceneIO's built-in file formats.

The parsers in this module stop at container headers whenever the format has
one. Headerless text formats are streamed line by line, and JSON scene formats
parse only their metadata document (they do not construct compiled records or
pixel/point arrays).
"""

from __future__ import annotations

import gzip
import math
import struct
import zipfile
from collections.abc import Callable
from collections.abc import Mapping as Mapping
from pathlib import Path
from typing import BinaryIO

import numpy as np

from sceneio import _core
from sceneio.io._inspectors.calibration import (
    inspect_camera_rig as _inspect_calibration_camera_rig,
)
from sceneio.io._inspectors.common import _HEADER_LIMIT as _HEADER_LIMIT
from sceneio.io._inspectors.common import _IMAGE_PIXEL_CAP as _IMAGE_PIXEL_CAP
from sceneio.io._inspectors.common import (
    _compiled_buffer_inspect,
    _exact,
    _image,
    _unsigned_decimal,
)
from sceneio.io._inspectors.images import (
    inspect_bmp as _inspect_image_bmp,
)
from sceneio.io._inspectors.images import (
    inspect_exr as _inspect_image_exr,
)
from sceneio.io._inspectors.images import (
    inspect_hdr as _inspect_image_hdr,
)
from sceneio.io._inspectors.images import (
    inspect_jpeg as _inspect_image_jpeg,
)
from sceneio.io._inspectors.images import (
    inspect_netpbm as _inspect_image_netpbm,
)
from sceneio.io._inspectors.images import (
    inspect_png as _inspect_image_png,
)
from sceneio.io._inspectors.images import (
    inspect_tga as _inspect_image_tga,
)
from sceneio.io._inspectors.images import (
    inspect_webp as _inspect_image_webp,
)
from sceneio.io._inspectors.meshes import (
    inspect_off as _inspect_mesh_off,
)
from sceneio.io._inspectors.meshes import (
    inspect_ply_mesh as _inspect_mesh_ply,
)
from sceneio.io._inspectors.meshes import (
    inspect_stl as _inspect_mesh_stl,
)
from sceneio.io._inspectors.model import (
    ArrayInspection,
    Inspection,
    MetadataValue,
)
from sceneio.io._pcd import parse_pcd_header, validate_point_pcd_header
from sceneio.io._ply import (
    parse_ply_header,
    validate_compressed_ply_header,
    validate_point_ply_header,
)


def inspect_path(path: str | Path, format_id: str, datatype: str) -> Inspection:
    """Inspect one built-in format without constructing its decoded record."""

    p = Path(path)
    if format_id == "pfm":
        return _inspect_pfm(p, datatype)
    if format_id == "colmap_sparse":
        return _inspect_colmap_binary(p, datatype)
    if format_id == "gaussian_ply":
        return _inspect_gaussian_ply(p, datatype)
    if format_id == "compressed_ply":
        return _inspect_compressed_ply(p, datatype)
    if format_id == "sog":
        return _inspect_sog(p, datatype)
    if format_id == "ksplat":
        return _inspect_ksplat(p, datatype)
    if format_id == "ply":
        return _inspect_ply(p, datatype)
    if format_id == "ply_mesh":
        return _inspect_ply_mesh(p, datatype)
    if format_id == "stl":
        return _inspect_stl(p, datatype)
    if format_id == "off":
        return _inspect_off(p, datatype)
    if format_id == "pcd":
        return _inspect_pcd(p, datatype)
    if format_id == "spz":
        return _inspect_spz(p, datatype)
    if format_id == "transforms_json":
        return _inspect_transforms(p, datatype)
    if format_id in {"tum", "kitti"}:
        return _inspect_pose_text(p, format_id, datatype)
    if format_id == "euroc_state":
        return _inspect_euroc_state(p, datatype)
    if format_id in {
        "opencv_yaml",
        "opencv_xml",
        "ros_camera_info",
        "kalibr",
    }:
        return _inspect_camera_rig(p, format_id, datatype)
    if format_id == "g2o":
        return _inspect_g2o(p, datatype)
    if format_id == "colmap_db":
        return _inspect_colmap_db(p, datatype)
    if format_id == "npy":
        return _inspect_npy(p, datatype)
    if format_id == "npz":
        return _inspect_npz(p, datatype)
    if format_id == "safetensors":
        return _inspect_safetensors(p, datatype)
    if format_id == "netpbm":
        return _inspect_netpbm(p, datatype)
    if format_id == "png":
        return _inspect_png(p, datatype)
    if format_id == "jpeg":
        return _inspect_jpeg(p, datatype)
    if format_id == "bmp":
        return _inspect_bmp(p, datatype)
    if format_id == "tga":
        return _inspect_tga(p, datatype)
    if format_id == "hdr":
        return _inspect_hdr(p, datatype)
    if format_id == "exr":
        return _inspect_exr(p, datatype)
    if format_id == "webp":
        return _inspect_webp(p, datatype)
    if format_id == "y4m":
        return _inspect_y4m(p, datatype)
    if format_id == "colmap_sparse_txt":
        return _inspect_colmap_text(p, datatype)
    if format_id == "xyz":
        return _inspect_xyz(p, datatype)
    if format_id == "pts":
        return _inspect_pts(p, datatype)
    if format_id == "las":
        return _inspect_las(p, datatype)
    if format_id == "laz":
        return _inspect_laz(p, datatype)
    if format_id == "flo":
        return _inspect_flo(p, datatype)
    if format_id == "dmb":
        return _inspect_dmb(p, datatype)
    if format_id == "bundler":
        return _inspect_bundler(p, datatype)
    if format_id == "bal":
        return _inspect_bal(p, datatype)
    if format_id == "nvm":
        return _inspect_nvm(p, datatype)
    if format_id == "openmvg":
        return _inspect_openmvg(p, datatype)
    if format_id == "splat":
        return _inspect_splat(p, datatype)
    raise ValueError(f"format {format_id!r} does not provide metadata inspection")


def inspect_codec(
    path: str | Path,
    format_id: str,
    datatype: str,
    inspector: Callable[[str], object] | None,
) -> Inspection:
    """Dispatch one already-resolved codec inspector without registry imports."""

    result = (
        inspect_path(path, format_id, datatype)
        if inspector is None
        else inspector(str(path))
    )
    if not isinstance(result, Inspection):
        raise TypeError(
            f"format {format_id!r} inspector returned {type(result).__name__}, "
            "expected Inspection"
        )
    return result


def _size(path: Path) -> int:
    return path.stat().st_size


def _inspect_colmap_db(path: Path, datatype: str) -> Inspection:
    """Inspect SQL metadata without fetching any feature/match BLOB."""

    values = _core.inspect_colmap_db(str(path))
    arrays = []
    for image_id, keypoint_count, keypoint_dim, descriptor_count, descriptor_dim in zip(
        values["image_ids"],
        values["keypoint_counts"],
        values["keypoint_dimensions"],
        values["descriptor_counts"],
        values["image_descriptor_dimensions"],
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
                    "uint8",
                )
            )
    return Inspection(
        format="colmap_db",
        datatype=datatype,
        byte_size=_size(path),
        shape=(values["num_images"],),
        count=values["num_images"],
        arrays=tuple(arrays),
        metadata={
            "user_version": values["user_version"],
            "sqlite_version": values["sqlite_version"],
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
        },
    )


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.iterdir() if item.is_file())


def _validate_classic_zip_extent(path: Path, format_name: str) -> None:
    size = _size(path)
    if size < 22:
        raise ValueError(f"{format_name}: malformed or empty ZIP archive")
    with path.open("rb") as stream:
        if _exact(stream, 4, f"{format_name} ZIP signature") != b"PK\x03\x04":
            raise ValueError(f"{format_name}: malformed or empty ZIP archive")
        tail_size = min(size, 22 + 65535)
        stream.seek(size - tail_size)
        tail = stream.read(tail_size)
    tail_base = size - tail_size
    eocd = None
    for offset in range(len(tail) - 22, -1, -1):
        if tail[offset : offset + 4] != b"PK\x05\x06":
            continue
        comment_size = struct.unpack_from("<H", tail, offset + 20)[0]
        if tail_base + offset + 22 + comment_size == size:
            eocd = tail_base + offset
            values = struct.unpack_from("<HHHHII", tail, offset + 4)
            break
    if eocd is None:
        raise ValueError(
            f"{format_name}: ZIP end record is missing or has trailing bytes"
        )
    disk, central_disk, disk_entries, entries, directory_size, directory_offset = (
        values
    )
    if disk != 0 or central_disk != 0:
        raise ValueError(f"{format_name}: multi-disk ZIP archives are unsupported")
    if (
        disk_entries == 0xFFFF
        or entries == 0xFFFF
        or directory_size == 0xFFFFFFFF
        or directory_offset == 0xFFFFFFFF
    ):
        raise ValueError(f"{format_name}: ZIP64 archives are unsupported")
    if (
        disk_entries != entries
        or directory_offset + directory_size != eocd
    ):
        raise ValueError(
            f"{format_name}: inconsistent ZIP central-directory extent"
        )


def _iter_data_lines(path: Path):
    with path.open("rb") as stream:
        while line := stream.readline(_HEADER_LIMIT + 2):
            content_size = len(line) - int(line.endswith(b"\n"))
            if content_size > _HEADER_LIMIT:
                raise ValueError("metadata line exceeds 1 MiB")
            stripped = line.strip()
            if stripped and not stripped.startswith(b"#"):
                yield stripped


def _inspect_pfm(path: Path, datatype: str) -> Inspection:
    height, width, channels, little_endian = _compiled_buffer_inspect(
        path, _core._inspect_pfm
    )
    return _image(
        "pfm",
        datatype,
        _size(path),
        height,
        width,
        channels,
        "float32",
        byte_order="little" if little_endian else "big",
    )


def _npy_header(stream: BinaryIO) -> tuple[tuple[int, ...], str, bool]:
    magic = _exact(stream, 6, "NPY magic")
    if magic != b"\x93NUMPY":
        raise ValueError("npy: bad magic")
    version = _exact(stream, 2, "NPY version")
    major, minor = version
    if major == 1:
        length_bytes = _exact(stream, 2, "NPY header length")
        header_size = struct.unpack("<H", length_bytes)[0]
    elif major in {2, 3}:
        length_bytes = _exact(stream, 4, "NPY header length")
        header_size = struct.unpack("<I", length_bytes)[0]
    else:
        raise ValueError(f"npy: unsupported format version {major}.{minor}")
    if header_size > _HEADER_LIMIT:
        raise ValueError("npy: header exceeds 1 MiB")
    header = _exact(stream, header_size, "NPY header")
    shape, dtype, fortran = _core._inspect_npy(
        magic + version + length_bytes + header
    )
    return tuple(shape), dtype, fortran


def _inspect_npy(path: Path, datatype: str) -> Inspection:
    shape, dtype, fortran = _compiled_buffer_inspect(path, _core._inspect_npy)
    shape = tuple(shape)
    count = math.prod(shape)
    return Inspection(
        "npy",
        datatype,
        _size(path),
        shape=shape,
        dtype=dtype,
        count=count,
        metadata={"fortran_order": fortran},
    )


def _inspect_npz(path: Path, datatype: str) -> Inspection:
    arrays = []
    with path.open("rb") as raw, zipfile.ZipFile(path) as archive:
        seen = set()
        for member in archive.infolist():
            raw.seek(member.header_offset)
            local = _exact(raw, 30, "NPZ local member header")
            if local[:4] != b"PK\x03\x04":
                raise ValueError("npz: malformed local member header")
            flags, method = struct.unpack_from("<HH", local, 6)
            name_size = struct.unpack_from("<H", local, 26)[0]
            raw_name = _exact(raw, name_size, "NPZ member filename")
            encoding = "utf-8" if member.flag_bits & 0x800 else "cp437"
            central_name = member.filename.encode(encoding)
            if raw_name != central_name:
                raise ValueError(
                    "npz: local and central member filenames disagree"
                )
            if flags != member.flag_bits:
                raise ValueError(
                    "npz: local and central member metadata disagree"
                )
            if method != member.compress_type:
                raise ValueError(
                    "npz: local and central member metadata disagree"
                )
            if member.is_dir():
                continue
            if b"\0" in raw_name:
                raise ValueError("npz: member filename contains NUL")
            try:
                filename = raw_name.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError("npz: member filename is not valid UTF-8") from None
            if method not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise ValueError("npz: only stored and deflate members are supported")
            if flags & 1:
                raise ValueError("npz: encrypted members are not supported")
            if filename.endswith("/"):
                continue
            name = filename.removesuffix(".npy")
            if name in seen:
                raise ValueError(f"npz: duplicate tensor name {name!r}")
            seen.add(name)
            with archive.open(member) as stream:
                shape, dtype, _ = _npy_header(stream)
            arrays.append(ArrayInspection(name, shape, dtype))
    return Inspection(
        "npz",
        datatype,
        _size(path),
        count=len(arrays),
        arrays=tuple(arrays),
    )


def _inspect_safetensors(path: Path, datatype: str) -> Inspection:
    arrays_raw, attrs = _compiled_buffer_inspect(
        path, _core._inspect_safetensors
    )
    arrays = tuple(
        ArrayInspection(name, tuple(shape), dtype)
        for name, shape, dtype in arrays_raw
    )
    return Inspection(
        "safetensors",
        datatype,
        _size(path),
        count=len(arrays),
        arrays=arrays,
        metadata={"metadata_keys": tuple(attrs)},
    )


def _inspect_netpbm(path: Path, datatype: str) -> Inspection:
    return _inspect_image_netpbm(path, datatype)


def _inspect_png(path: Path, datatype: str) -> Inspection:
    return _inspect_image_png(path, datatype)


def _inspect_jpeg(path: Path, datatype: str) -> Inspection:
    return _inspect_image_jpeg(path, datatype)


def _inspect_bmp(path: Path, datatype: str) -> Inspection:
    return _inspect_image_bmp(path, datatype)


def _inspect_tga(path: Path, datatype: str) -> Inspection:
    return _inspect_image_tga(path, datatype)


def _inspect_hdr(path: Path, datatype: str) -> Inspection:
    return _inspect_image_hdr(path, datatype)


def _inspect_exr(path: Path, datatype: str) -> Inspection:
    return _inspect_image_exr(path, datatype)


def _inspect_webp(path: Path, datatype: str) -> Inspection:
    return _inspect_image_webp(path, datatype)

def _inspect_y4m(path: Path, datatype: str) -> Inspection:
    values = dict(_compiled_buffer_inspect(path, _core._inspect_y4m))
    frames = values["frames"]
    height = values["height"]
    width = values["width"]
    channels = values["channels"]
    arrays = [
        ArrayInspection("y", (frames, height, width), "uint8"),
    ]
    if channels == 3:
        chroma_shape = (
            frames,
            values["chroma_height"],
            values["chroma_width"],
        )
        arrays.extend(
            (
                ArrayInspection("u", chroma_shape, "uint8"),
                ArrayInspection("v", chroma_shape, "uint8"),
            )
        )
    return Inspection(
        format="y4m",
        datatype=datatype,
        byte_size=_size(path),
        shape=(frames, height, width, channels),
        dtype="uint8",
        count=frames,
        channels=channels,
        arrays=tuple(arrays),
        metadata={
            "storage_mode": "yuv_planar",
            "chroma_subsampling": values["chroma_subsampling"],
            "chroma_siting": values["chroma_siting"],
            "color_range": values["color_range"],
            "matrix": values["matrix"],
            "interlace": values["interlace"],
            "frame_rate_numerator": values["frame_rate_numerator"],
            "frame_rate_denominator": values["frame_rate_denominator"],
            "pixel_aspect_numerator": values["pixel_aspect_numerator"],
            "pixel_aspect_denominator": values["pixel_aspect_denominator"],
            "frame_bytes": values["frame_bytes"],
        },
    )


def _inspect_flo(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    with path.open("rb") as stream:
        header = _exact(stream, 12, "FLO header")
    if header[:4] != b"PIEH":
        raise ValueError("flo: bad magic")
    width, height = struct.unpack_from("<ii", header, 4)
    expected = 12 + width * height * 2 * 4
    if width < 1 or height < 1 or expected > file_size:
        raise ValueError("flo: invalid dimensions or payload size")
    return _image("flo", datatype, file_size, height, width, 2, "float32")


def _inspect_dmb(path: Path, datatype: str) -> Inspection:
    height, width, channels, image_type = _compiled_buffer_inspect(
        path, _core._inspect_dmb
    )
    return Inspection(
        "dmb",
        datatype,
        _size(path),
        shape=(height, width),
        dtype="float32",
        count=height * width,
        channels=channels,
        metadata={
            "channels": channels,
            "image_type": image_type,
            "unit": "unknown",
            "scale_to_meters": 0.0,
            "invalid_policy": "zero",
        },
    )


def _inspect_las(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    with path.open("rb") as stream:
        header = _exact(stream, min(255, file_size), "LAS public header")
    if len(header) < 227 or header[:4] != b"LASF":
        raise ValueError("las: bad or truncated public header")
    major, minor = header[24], header[25]
    if major != 1 or minor not in {1, 2, 3, 4}:
        raise ValueError("las: supported versions are 1.1 through 1.4")
    required_header = 375 if minor == 4 else 235 if minor == 3 else 227
    if file_size < required_header or len(header) < min(required_header, 255):
        raise ValueError("las: truncated public header")
    header_size = struct.unpack_from("<H", header, 94)[0]
    point_format = header[104]
    if point_format & 0xC0:
        raise ValueError("las: compressed LAZ is unsupported")
    format_id = point_format
    if format_id not in set(range(11)):
        raise ValueError(f"las: unsupported point format {format_id}")
    if format_id in {4, 5} and minor < 3:
        raise ValueError("las: point formats 4/5 require LAS 1.3 or newer")
    if format_id in {6, 7, 8, 9, 10} and minor < 4:
        raise ValueError("las: point formats 6-10 require LAS 1.4")
    if major == 1 and minor >= 4:
        if len(header) < 255:
            raise ValueError("las: truncated LAS 1.4 header")
        count = struct.unpack_from("<Q", header, 247)[0]
    else:
        count = struct.unpack_from("<I", header, 107)[0]
    offset_to_points = struct.unpack_from("<I", header, 96)[0]
    record_length = struct.unpack_from("<H", header, 105)[0]
    scales = struct.unpack_from("<ddd", header, 131)
    offsets = struct.unpack_from("<ddd", header, 155)
    if any(not math.isfinite(value) or value <= 0 for value in scales):
        raise ValueError("las: coordinate scales must be finite and positive")
    if any(not math.isfinite(value) for value in offsets):
        raise ValueError("las: coordinate offsets must be finite")
    minimum_length = {
        0: 20,
        1: 28,
        2: 26,
        3: 34,
        4: 57,
        5: 63,
        6: 30,
        7: 36,
        8: 38,
        9: 59,
        10: 67,
    }[format_id]
    if record_length < minimum_length:
        raise ValueError("las: point record length is too short")
    if count > 4_000_000_000:
        raise ValueError("las: point count exceeds the supported limit")
    if (
        header_size < required_header
        or offset_to_points < required_header
        or offset_to_points + count * record_length > file_size
    ):
        raise ValueError("las: truncated or malformed point data")
    return Inspection(
        "las",
        datatype,
        file_size,
        shape=(count, 3),
        dtype="float32",
        count=count,
        metadata={
            "point_format": format_id,
            "has_color": format_id in {2, 3, 5, 7, 8, 10},
            "has_intensity": True,
            "has_waveform": format_id in {4, 5, 9, 10},
        },
    )


def _inspect_laz(path: Path, datatype: str) -> Inspection:
    """Inspect the LAS public header and LASzip VLR without decoding chunks."""

    file_size = _size(path)
    with path.open("rb") as stream:
        header = _exact(stream, min(375, file_size), "LAZ public header")
        if len(header) < 227 or header[:4] != b"LASF":
            raise ValueError("laz: bad or truncated public header")
        major, minor = header[24], header[25]
        if major != 1 or minor not in {1, 2, 3, 4}:
            raise ValueError("laz: supported versions are 1.1 through 1.4")
        required_header = 375 if minor == 4 else 235 if minor == 3 else 227
        if file_size < required_header or len(header) < required_header:
            raise ValueError("laz: truncated public header")
        global_encoding = struct.unpack_from("<H", header, 6)[0]
        if global_encoding & 0xFFFE:
            raise ValueError("laz: global-encoding metadata is not representable")

        header_size = struct.unpack_from("<H", header, 94)[0]
        point_offset = struct.unpack_from("<I", header, 96)[0]
        vlr_count = struct.unpack_from("<I", header, 100)[0]
        encoded_format = header[104]
        if encoded_format & 0xC0 != 0x80:
            raise ValueError("laz: header does not use supported compression bits")
        point_format = encoded_format & 0x3F
        if point_format not in {0, 1, 2, 3, 6, 7, 8}:
            raise ValueError(f"laz: unsupported point format {point_format}")
        if point_format >= 6 and minor < 4:
            raise ValueError("laz: point formats 6-8 require LAS 1.4")
        if header_size != required_header:
            raise ValueError("laz: extended public headers are not representable")
        if vlr_count != 1:
            raise ValueError("laz: exactly one LASzip VLR is required")
        if point_offset < header_size + 54 or point_offset > file_size:
            raise ValueError("laz: truncated or malformed VLR region")

        record_length = struct.unpack_from("<H", header, 105)[0]
        expected_length = {0: 20, 1: 28, 2: 26, 3: 34, 6: 30, 7: 36, 8: 38}[
            point_format
        ]
        if record_length != expected_length:
            raise ValueError(
                "laz: extra bytes and nonstandard point strides are not representable"
            )
        count = (
            struct.unpack_from("<Q", header, 247)[0]
            if minor == 4
            else struct.unpack_from("<I", header, 107)[0]
        )
        scales = struct.unpack_from("<ddd", header, 131)
        offsets = struct.unpack_from("<ddd", header, 155)
        if any(not math.isfinite(value) or value <= 0 for value in scales):
            raise ValueError("laz: coordinate scales must be finite and positive")
        if any(not math.isfinite(value) for value in offsets):
            raise ValueError("laz: coordinate offsets must be finite")
        if minor >= 3 and struct.unpack_from("<Q", header, 227)[0] != 0:
            raise ValueError("laz: waveform packet records are not representable")
        if minor >= 4:
            evlr_offset = struct.unpack_from("<Q", header, 235)[0]
            evlr_count = struct.unpack_from("<I", header, 243)[0]
            if evlr_offset != 0 or evlr_count != 0:
                raise ValueError("laz: EVLR metadata is not representable")
        if count > 4_000_000_000:
            raise ValueError("laz: point count exceeds the supported limit")

        stream.seek(header_size)
        vlr_header = _exact(stream, 54, "LAZ LASzip VLR header")
        reserved = struct.unpack_from("<H", vlr_header, 0)[0]
        user_id = vlr_header[2:18].rstrip(b"\0 ")
        record_id = struct.unpack_from("<H", vlr_header, 18)[0]
        payload_size = struct.unpack_from("<H", vlr_header, 20)[0]
        if reserved != 0 or user_id != b"laszip encoded" or record_id != 22204:
            raise ValueError("laz: the sole VLR must be the LASzip VLR")
        if header_size + 54 + payload_size != point_offset:
            raise ValueError("laz: VLR extent disagrees with point-data offset")
        payload = _exact(stream, payload_size, "LAZ LASzip VLR payload")
        stream.seek(point_offset)
        table_offset = struct.unpack(
            "<q", _exact(stream, 8, "LAZ chunk-table pointer")
        )[0]
        if (
            table_offset < point_offset + 8
            or table_offset > file_size - 8
        ):
            raise ValueError("laz: chunk-table offset is out of bounds")
        stream.seek(table_offset)
        table_version, chunk_count = struct.unpack(
            "<II", _exact(stream, 8, "LAZ chunk-table header")
        )

    if payload_size < 34:
        raise ValueError("laz: LASzip VLR is truncated")
    compressor, coder, _version_major, _version_minor = struct.unpack_from(
        "<HHBB", payload
    )
    expected_compressor = 2 if point_format <= 3 else 3
    if compressor != expected_compressor or coder != 0:
        raise ValueError("laz: unsupported LASzip codec metadata")
    options = struct.unpack_from("<I", payload, 8)[0]
    chunk_size = struct.unpack_from("<I", payload, 12)[0]
    item_count = struct.unpack_from("<H", payload, 32)[0]
    if options != 0 or chunk_size == 0:
        raise ValueError("laz: unsupported LASzip options or chunk size")
    if table_version != 0:
        raise ValueError("laz: unsupported chunk-table version")
    if chunk_count > 4_000_000:
        raise ValueError("laz: chunk count exceeds the supported limit")
    if chunk_size != 0xFFFFFFFF:
        expected_chunks = 0 if count == 0 else 1 + (count - 1) // chunk_size
        if chunk_count != expected_chunks:
            raise ValueError("laz: fixed chunk count disagrees with point count")
    if count == 0 and table_offset + 8 != file_size:
        raise ValueError("laz: trailing bytes after empty chunk table")
    if payload_size != 34 + item_count * 6:
        raise ValueError("laz: malformed LASzip item table")
    expected_items = {
        0: ((6, 20, 2),),
        1: ((6, 20, 2), (7, 8, 2)),
        2: ((6, 20, 2), (8, 6, 2)),
        3: ((6, 20, 2), (7, 8, 2), (8, 6, 2)),
        6: ((10, 30, 3),),
        7: ((10, 30, 3), (11, 6, 3)),
        8: ((10, 30, 3), (12, 8, 3)),
    }[point_format]
    items = tuple(
        struct.unpack_from("<HHH", payload, 34 + index * 6)
        for index in range(item_count)
    )
    if items != expected_items:
        raise ValueError("laz: LASzip item schema disagrees with point format")
    if count and point_offset + 8 > file_size:
        raise ValueError("laz: truncated compressed point data")

    return Inspection(
        "laz",
        datatype,
        file_size,
        shape=(count, 3),
        dtype="float32",
        count=count,
        metadata={
            "point_format": point_format,
            "has_color": point_format in {2, 3, 7, 8},
            "has_intensity": True,
            "has_waveform": False,
            "chunk_size": chunk_size,
        },
    )


def _inspect_gaussian_ply(path: Path, datatype: str) -> Inspection:
    count = None
    required_names = {
        b"x",
        b"y",
        b"z",
        b"f_dc_0",
        b"f_dc_1",
        b"f_dc_2",
        b"opacity",
        b"scale_0",
        b"scale_1",
        b"scale_2",
        b"rot_0",
        b"rot_1",
        b"rot_2",
        b"rot_3",
    }
    seen_required = set()
    rest_indices = set()
    current_element = None
    byte_order = None
    line_limit = 4096
    with path.open("rb") as stream:
        first = stream.readline(line_limit + 1)
        if len(first) > line_limit:
            raise ValueError("PLY: header line is too long")
        if first.rstrip(b"\r\n") != b"ply":
            raise ValueError("PLY: bad magic")
        while True:
            line = stream.readline(line_limit + 1)
            if not line:
                raise ValueError("PLY: missing end_header")
            if len(line) > line_limit:
                raise ValueError("PLY: header line is too long")
            tokens = line.strip().split(maxsplit=3)
            if not tokens or tokens[0] == b"comment":
                continue
            if tokens[0] == b"format":
                if len(tokens) != 3 or tokens[2] != b"1.0" or byte_order is not None:
                    raise ValueError("PLY: malformed or duplicate format header")
                if tokens[1] == b"binary_little_endian":
                    byte_order = "little"
                elif tokens[1] == b"binary_big_endian":
                    byte_order = "big"
                else:
                    raise ValueError("PLY: unsupported format")
            elif tokens[0] == b"element":
                if len(tokens) != 3:
                    raise ValueError("PLY: malformed element header")
                current_element = tokens[1]
                if current_element == b"vertex":
                    count = _unsigned_decimal(tokens[2], "PLY vertex count")
                    if count > np.iinfo(np.uintp).max:
                        raise ValueError("PLY: malformed vertex count")
            elif tokens[0] == b"property" and current_element == b"vertex":
                if len(tokens) != 3 or tokens[1] not in {b"float", b"float32"}:
                    raise ValueError("PLY: only float32 vertex properties are supported")
                name = tokens[2]
                if name in required_names:
                    seen_required.add(name)
                elif name.startswith(b"f_rest_"):
                    suffix = name[len(b"f_rest_") :]
                    if suffix.isdigit():
                        index = int(suffix)
                        if suffix == str(index).encode() and index <= 45:
                            rest_indices.add(index)
            elif tokens[0] == b"end_header":
                if tokens != [b"end_header"]:
                    raise ValueError("PLY: malformed end_header")
                break
    if byte_order is None or count is None:
        raise ValueError("PLY: missing binary format or vertex count")
    missing = required_names - seen_required
    if missing:
        raise ValueError(f"PLY: missing Gaussian property {min(missing).decode()!r}")
    rest = 0
    while rest in rest_indices:
        rest += 1
    if rest not in {0, 9, 24, 45}:
        raise ValueError("PLY: unsupported SH property count")
    degree = {0: 0, 9: 1, 24: 2, 45: 3}[rest]
    return Inspection(
        "gaussian_ply",
        datatype,
        _size(path),
        shape=(count,),
        dtype="float32",
        count=count,
        metadata={
            "sh_degree": degree,
            "num_rest": rest,
            "byte_order": byte_order,
        },
    )


def _inspect_compressed_ply(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    header = parse_ply_header(path)
    metadata = validate_compressed_ply_header(header, file_size)
    vertex = next(
        element for element in header.elements if element.name == b"vertex"
    )
    return Inspection(
        "compressed_ply",
        datatype,
        file_size,
        shape=(vertex.count,),
        dtype="float32",
        count=vertex.count,
        metadata=metadata,
    )


def _inspect_sog(path: Path, datatype: str) -> Inspection:
    metadata_path = path / "meta.json" if path.is_dir() else path
    if metadata_path.name == "meta.json":
        if metadata_path.stat().st_size > _HEADER_LIMIT:
            raise ValueError("sog: meta.json exceeds 1 MiB")
        with metadata_path.open("rb") as stream:
            metadata_bytes = stream.read(_HEADER_LIMIT + 1)
        if len(metadata_bytes) > _HEADER_LIMIT:
            raise ValueError("sog: meta.json exceeds 1 MiB")
        count, bands, rest, palette_count, declared = (
            _core._inspect_sog_metadata(metadata_bytes)
        )
        declared = set(declared)
        parent = metadata_path.parent
        missing = [
            name
            for name in declared
            if not (parent / name).is_file()
        ]
        if missing:
            raise ValueError(
                f"sog: missing declared layer {min(missing)!r}"
            )
        byte_size = sum((parent / name).stat().st_size for name in declared)
        packaging = "directory"
    else:
        _validate_classic_zip_extent(path, "sog")
        with path.open("rb") as raw, zipfile.ZipFile(path) as archive:
            members = {}
            for member in archive.infolist():
                raw.seek(member.header_offset)
                local = _exact(raw, 30, "SOG local member header")
                if local[:4] != b"PK\x03\x04":
                    raise ValueError("sog: malformed local ZIP member header")
                flags, method = struct.unpack_from("<HH", local, 6)
                name_size = struct.unpack_from("<H", local, 26)[0]
                raw_name = _exact(raw, name_size, "SOG member filename")
                encoding = "utf-8" if member.flag_bits & 0x800 else "cp437"
                if raw_name != member.filename.encode(encoding):
                    raise ValueError(
                        "sog: local and central ZIP filenames disagree"
                    )
                if flags != member.flag_bits or method != member.compress_type:
                    raise ValueError(
                        "sog: local and central ZIP metadata disagree"
                    )
                if member.is_dir():
                    raise ValueError("sog: directory ZIP entries are unsupported")
                if flags & 1:
                    raise ValueError("sog: encrypted ZIP members are unsupported")
                if method not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise ValueError(
                        "sog: only stored and deflated ZIP members are supported"
                    )
                try:
                    name = raw_name.decode("utf-8")
                except UnicodeDecodeError:
                    raise ValueError(
                        "sog: ZIP member filename is not valid UTF-8"
                    ) from None
                if name in members:
                    raise ValueError(f"sog: duplicate ZIP member {name!r}")
                members[name] = member
            try:
                meta_member = members["meta.json"]
            except KeyError:
                raise ValueError("sog: missing ZIP member 'meta.json'") from None
            if meta_member.file_size > _HEADER_LIMIT:
                raise ValueError("sog: meta.json exceeds 1 MiB")
            metadata_bytes = archive.read(meta_member)
            count, bands, rest, palette_count, declared = (
                _core._inspect_sog_metadata(metadata_bytes)
            )
            if set(members) != set(declared):
                raise ValueError(
                    "sog: ZIP members do not exactly match declared layers"
                )
        byte_size = _size(path)
        packaging = "zip"
    return Inspection(
        "sog",
        datatype,
        byte_size,
        shape=(count,),
        dtype="float32",
        count=count,
        metadata={
            "version": 2,
            "sh_degree": bands,
            "num_rest": rest,
            "palette_count": palette_count,
            "packaging": packaging,
            "texture_codec": "lossless_webp",
        },
    )


def _inspect_ksplat(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    if file_size < 4096:
        raise ValueError("ksplat: truncated 4096-byte header")
    with path.open("rb") as stream:
        base = _exact(stream, 4096, "KSplat header")
        section_count = struct.unpack_from("<I", base, 4)[0]
        header_extent = 4096 + section_count * 1024
        if header_extent > file_size:
            raise ValueError("ksplat: truncated section headers")
        section_headers = _exact(
            stream,
            header_extent - 4096,
            "KSplat section headers",
        )
    (
        count,
        degree,
        compression,
        declared_sections,
        loaded_sections,
        loaded_count,
        scene_x,
        scene_y,
        scene_z,
        sh_min,
        sh_max,
    ) = _core._inspect_ksplat_metadata(
        base + section_headers,
        file_size,
    )
    return Inspection(
        "ksplat",
        datatype,
        file_size,
        shape=(count,),
        dtype="float32",
        count=count,
        metadata={
            "version": "0.1",
            "compression_level": compression,
            "sh_degree": degree,
            "num_rest": (0, 9, 24)[degree],
            "section_count": declared_sections,
            "loaded_section_count": loaded_sections,
            "loaded_count": loaded_count,
            "scene_center": (scene_x, scene_y, scene_z),
            "sh_quantization_range": (sh_min, sh_max),
        },
    )


def _inspect_ply(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    header = parse_ply_header(path)
    metadata = validate_point_ply_header(header, file_size)
    count = header.vertex.count
    return Inspection(
        "ply",
        datatype,
        file_size,
        shape=(count, 3),
        dtype="float32",
        count=count,
        metadata=metadata,
    )


def _inspect_ply_mesh(path: Path, datatype: str) -> Inspection:
    return _inspect_mesh_ply(path, datatype)


def _inspect_stl(path: Path, datatype: str) -> Inspection:
    return _inspect_mesh_stl(path, datatype)


def _inspect_off(path: Path, datatype: str) -> Inspection:
    return _inspect_mesh_off(path, datatype)


def _inspect_pcd(path: Path, datatype: str) -> Inspection:
    file_size = _size(path)
    header = parse_pcd_header(path)
    metadata = validate_point_pcd_header(header, path)
    return Inspection(
        "pcd",
        datatype,
        file_size,
        shape=(header.points, 3),
        dtype="float32",
        count=header.points,
        metadata=metadata,
    )


def _inspect_spz(path: Path, datatype: str) -> Inspection:
    with path.open("rb") as stream:
        prefix = _exact(stream, min(32, _size(path)), "SPZ header")
    if prefix.startswith(b"\x1f\x8b"):
        with gzip.open(path, "rb") as stream:
            header = _exact(stream, 16, "legacy SPZ header")
        magic, version, count = struct.unpack_from("<III", header)
        degree = header[12]
        fractional_bits = header[13]
        if magic != 0x5053474E or version not in {1, 2, 3}:
            raise ValueError("SPZ: bad legacy header")
    else:
        if len(prefix) < 32:
            raise ValueError("SPZ: truncated v4 header")
        magic, version, count = struct.unpack_from("<III", prefix)
        degree = prefix[12]
        fractional_bits = prefix[13]
        if magic != 0x5053474E or version != 4:
            raise ValueError("SPZ: bad v4 header")
    if degree not in {0, 1, 2, 3}:
        raise ValueError("SPZ: unsupported SH degree")
    if not 1 <= fractional_bits <= 24:
        raise ValueError("SPZ: invalid fractional_bits")
    return Inspection(
        "spz",
        datatype,
        _size(path),
        shape=(count,),
        dtype="float32",
        count=count,
        metadata={
            "version": version,
            "sh_degree": degree,
            "fractional_bits": fractional_bits,
        },
    )


def _inspect_splat(path: Path, datatype: str) -> Inspection:
    size = _size(path)
    if size % 32:
        raise ValueError("splat: size is not a multiple of 32")
    count = size // 32
    return Inspection(
        "splat",
        datatype,
        size,
        shape=(count,),
        dtype="float32",
        count=count,
        metadata={"sh_degree": 0},
    )


def _inspect_xyz(path: Path, datatype: str) -> Inspection:
    count, columns = _core._inspect_xyz_file(path)
    return Inspection(
        "xyz",
        datatype,
        _size(path),
        shape=(count, 3),
        dtype="float32",
        count=count,
        metadata={
            "columns": columns,
            "has_color": columns in {6, 7, 9},
            "has_intensity": columns in {4, 7},
            "has_normals": columns == 9,
        },
    )


def _inspect_pts(path: Path, datatype: str) -> Inspection:
    count = _compiled_buffer_inspect(path, _core._inspect_pts)
    return Inspection(
        "pts",
        datatype,
        _size(path),
        shape=(count, 3),
        dtype="float32",
        count=count,
        metadata={"declared_count": count},
    )


def _inspect_pose_text(path: Path, format_id: str, datatype: str) -> Inspection:
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


def _inspect_euroc_state(path: Path, datatype: str) -> Inspection:
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


def _inspect_camera_rig(
    path: Path, format_id: str, datatype: str
) -> Inspection:
    return _inspect_calibration_camera_rig(
        path,
        format_id,
        datatype,
    )


def _inspect_g2o(path: Path, datatype: str) -> Inspection:
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


def _inspect_bundler(path: Path, datatype: str) -> Inspection:
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


def _inspect_bal(path: Path, datatype: str) -> Inspection:
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


def _inspect_nvm(path: Path, datatype: str) -> Inspection:
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


def _inspect_transforms(path: Path, datatype: str) -> Inspection:
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


def _inspect_openmvg(path: Path, datatype: str) -> Inspection:
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


def _inspect_colmap_binary(path: Path, datatype: str) -> Inspection:
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


def _inspect_colmap_text(path: Path, datatype: str) -> Inspection:
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
