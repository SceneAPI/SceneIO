"""Metadata-only inspection for SceneIO's built-in file formats.

The parsers in this module stop at container headers whenever the format has
one. Headerless text formats are streamed line by line, and JSON scene formats
parse only their metadata document (they do not construct compiled records or
pixel/point arrays).
"""

from __future__ import annotations

import gzip
import struct
import zipfile
from collections.abc import Callable
from collections.abc import Mapping as Mapping
from pathlib import Path
from typing import BinaryIO

import numpy as np

from sceneio import _core
from sceneio.io._inspectors.arrays import (
    inspect_dmb as _inspect_array_dmb,
)
from sceneio.io._inspectors.arrays import (
    inspect_flo as _inspect_array_flo,
)
from sceneio.io._inspectors.arrays import (
    inspect_npy as _inspect_array_npy,
)
from sceneio.io._inspectors.arrays import (
    inspect_npz as _inspect_array_npz,
)
from sceneio.io._inspectors.arrays import (
    inspect_pfm as _inspect_array_pfm,
)
from sceneio.io._inspectors.arrays import (
    inspect_safetensors as _inspect_array_safetensors,
)
from sceneio.io._inspectors.arrays import (
    npy_header as _inspect_array_npy_header,
)
from sceneio.io._inspectors.calibration import (
    inspect_camera_rig as _inspect_calibration_camera_rig,
)
from sceneio.io._inspectors.common import _HEADER_LIMIT as _HEADER_LIMIT
from sceneio.io._inspectors.common import _IMAGE_PIXEL_CAP as _IMAGE_PIXEL_CAP
from sceneio.io._inspectors.common import (
    _compiled_buffer_inspect as _compiled_buffer_inspect,
)
from sceneio.io._inspectors.common import (
    _exact,
    _unsigned_decimal,
)
from sceneio.io._inspectors.common import _image as _image
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
from sceneio.io._inspectors.model import ArrayInspection as ArrayInspection
from sceneio.io._inspectors.model import Inspection
from sceneio.io._inspectors.model import MetadataValue as MetadataValue
from sceneio.io._inspectors.points import (
    inspect_las as _inspect_point_las,
)
from sceneio.io._inspectors.points import (
    inspect_laz as _inspect_point_laz,
)
from sceneio.io._inspectors.points import (
    inspect_pcd as _inspect_point_pcd,
)
from sceneio.io._inspectors.points import (
    inspect_ply as _inspect_point_ply,
)
from sceneio.io._inspectors.points import (
    inspect_pts as _inspect_point_pts,
)
from sceneio.io._inspectors.points import (
    inspect_xyz as _inspect_point_xyz,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_bal as _inspect_reconstruction_bal,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_bundler as _inspect_reconstruction_bundler,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_colmap_binary as _inspect_reconstruction_colmap_binary,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_colmap_db as _inspect_reconstruction_colmap_db,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_colmap_text as _inspect_reconstruction_colmap_text,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_euroc_state as _inspect_reconstruction_euroc_state,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_g2o as _inspect_reconstruction_g2o,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_nvm as _inspect_reconstruction_nvm,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_openmvg as _inspect_reconstruction_openmvg,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_pose_text as _inspect_reconstruction_pose_text,
)
from sceneio.io._inspectors.reconstruction import (
    inspect_transforms as _inspect_reconstruction_transforms,
)
from sceneio.io._inspectors.sequences import (
    inspect_y4m as _inspect_sequence_y4m,
)
from sceneio.io._ply import (
    parse_ply_header,
    validate_compressed_ply_header,
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
    return _inspect_reconstruction_colmap_db(path, datatype)


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


def _inspect_pfm(path: Path, datatype: str) -> Inspection:
    return _inspect_array_pfm(path, datatype)


def _npy_header(stream: BinaryIO) -> tuple[tuple[int, ...], str, bool]:
    return _inspect_array_npy_header(stream)


def _inspect_npy(path: Path, datatype: str) -> Inspection:
    return _inspect_array_npy(path, datatype)


def _inspect_npz(path: Path, datatype: str) -> Inspection:
    return _inspect_array_npz(path, datatype)


def _inspect_safetensors(path: Path, datatype: str) -> Inspection:
    return _inspect_array_safetensors(path, datatype)


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
    return _inspect_sequence_y4m(path, datatype)


def _inspect_flo(path: Path, datatype: str) -> Inspection:
    return _inspect_array_flo(path, datatype)


def _inspect_dmb(path: Path, datatype: str) -> Inspection:
    return _inspect_array_dmb(path, datatype)


def _inspect_las(path: Path, datatype: str) -> Inspection:
    return _inspect_point_las(path, datatype)


def _inspect_laz(path: Path, datatype: str) -> Inspection:
    return _inspect_point_laz(path, datatype)


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
    return _inspect_point_ply(path, datatype)


def _inspect_ply_mesh(path: Path, datatype: str) -> Inspection:
    return _inspect_mesh_ply(path, datatype)


def _inspect_stl(path: Path, datatype: str) -> Inspection:
    return _inspect_mesh_stl(path, datatype)


def _inspect_off(path: Path, datatype: str) -> Inspection:
    return _inspect_mesh_off(path, datatype)


def _inspect_pcd(path: Path, datatype: str) -> Inspection:
    return _inspect_point_pcd(path, datatype)


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
    return _inspect_point_xyz(path, datatype)


def _inspect_pts(path: Path, datatype: str) -> Inspection:
    return _inspect_point_pts(path, datatype)


def _inspect_pose_text(path: Path, format_id: str, datatype: str) -> Inspection:
    return _inspect_reconstruction_pose_text(path, format_id, datatype)


def _inspect_euroc_state(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_euroc_state(path, datatype)


def _inspect_camera_rig(
    path: Path, format_id: str, datatype: str
) -> Inspection:
    return _inspect_calibration_camera_rig(
        path,
        format_id,
        datatype,
    )


def _inspect_g2o(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_g2o(path, datatype)


def _inspect_bundler(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_bundler(path, datatype)


def _inspect_bal(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_bal(path, datatype)


def _inspect_nvm(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_nvm(path, datatype)


def _inspect_transforms(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_transforms(path, datatype)


def _inspect_openmvg(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_openmvg(path, datatype)


def _inspect_colmap_binary(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_colmap_binary(path, datatype)


def _inspect_colmap_text(path: Path, datatype: str) -> Inspection:
    return _inspect_reconstruction_colmap_text(path, datatype)
