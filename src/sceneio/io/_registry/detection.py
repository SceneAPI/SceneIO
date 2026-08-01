"""Ordered format detection independent of the registry facade."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from sceneio.io._registry.model import Codec


def _generic_hdf5(_path: Path) -> str:
    return "hdf5"


def _is_apng(path: Path) -> bool:
    """Classify APNG from its acTL chunk without reading compressed pixels."""

    try:
        file_size = path.stat().st_size
        with path.open("rb") as stream:
            if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                return False
            while stream.tell() + 12 <= file_size:
                chunk_header = stream.read(8)
                if len(chunk_header) != 8:
                    return False
                chunk_size = int.from_bytes(chunk_header[:4], "big")
                chunk_type = chunk_header[4:]
                chunk_end = stream.tell() + chunk_size + 4
                if chunk_size > 0x7FFF_FFFF or chunk_end > file_size:
                    return False
                if chunk_type == b"acTL":
                    return chunk_size == 8
                if chunk_type in {b"IDAT", b"IEND"}:
                    return False
                stream.seek(chunk_end)
    except OSError:
        return False
    return False


def _is_animated_webp(path: Path) -> bool:
    """Classify WebP animation from RIFF chunks without reading frame payloads."""

    try:
        file_size = path.stat().st_size
        with path.open("rb") as stream:
            header = stream.read(12)
            if (
                len(header) != 12
                or header[:4] != b"RIFF"
                or header[8:] != b"WEBP"
            ):
                return False
            riff_end = min(
                file_size,
                8 + int.from_bytes(header[4:8], "little"),
            )
            while stream.tell() + 8 <= riff_end:
                chunk_header = stream.read(8)
                if len(chunk_header) != 8:
                    return False
                fourcc = chunk_header[:4]
                chunk_size = int.from_bytes(chunk_header[4:], "little")
                payload_start = stream.tell()
                padded_end = payload_start + chunk_size + (chunk_size & 1)
                if padded_end > riff_end:
                    return fourcc in {b"ANIM", b"ANMF"}
                if fourcc in {b"ANIM", b"ANMF"}:
                    return True
                stream.seek(padded_end)
    except OSError:
        return False
    return False


def _avif_brand(path: Path) -> str | None:
    """Return ``avif`` or ``avis`` from a bounded ISO-BMFF file-type box."""

    try:
        file_size = path.stat().st_size
        with path.open("rb") as stream:
            prefix = stream.read(min(file_size, 65_536 + 4096 + 16))
            offset = 0
            while offset + 8 <= file_size and offset < 65_536:
                if offset + 8 > len(prefix):
                    return None
                box_size = int.from_bytes(prefix[offset : offset + 4], "big")
                box_type = prefix[offset + 4 : offset + 8]
                header_size = 8
                if box_size == 1:
                    if offset + 16 > len(prefix):
                        return None
                    box_size = int.from_bytes(prefix[offset + 8 : offset + 16], "big")
                    header_size = 16
                elif box_size == 0:
                    box_size = file_size - offset
                if box_size < header_size or box_size > file_size - offset:
                    return None
                if box_type == b"ftyp":
                    payload_size = box_size - header_size
                    if payload_size < 8 or payload_size > 4096:
                        return None
                    payload_start = offset + header_size
                    payload_end = payload_start + payload_size
                    if payload_end > len(prefix):
                        return None
                    payload = prefix[payload_start:payload_end]
                    brands = (
                        payload[:4],
                        *(
                            payload[index : index + 4]
                            for index in range(8, len(payload), 4)
                            if index + 4 <= len(payload)
                        ),
                    )
                    if b"avis" in brands:
                        return "avis"
                    if b"avif" in brands:
                        return "avif"
                    return None
                offset += box_size
    except OSError:
        return None
    return None


def _could_be_isobmff(head: bytes) -> bool:
    """Recognize bounded top-level boxes worth probing for extensionless AVIF."""

    if len(head) < 8:
        return False
    box_size = int.from_bytes(head[:4], "big")
    box_type = head[4:8]
    if box_type not in {b"free", b"ftyp", b"skip", b"uuid", b"wide"}:
        return False
    if box_size == 1:
        return len(head) >= 16 and int.from_bytes(head[8:16], "big") >= 16
    return box_size == 0 or box_size >= 8


def detect_path(
    path,
    codecs: Iterable[Codec],
    *,
    classify_ply: Callable[[Path], str],
    classify_hdf5: Callable[[Path], str] = _generic_hdf5,
    format_error: Callable[[str], Exception],
) -> str:
    """Detect ``path`` using the supplied canonical codec order."""

    p = Path(path)
    ordered = tuple(codecs)
    if p.is_dir():
        for codec in ordered:
            if codec.is_directory and any(
                (p / marker).exists() for marker in codec.directory_markers
            ):
                return codec.id
        raise format_error(f"no directory format matches {str(path)!r}")
    for codec in ordered:
        if p.name in codec.filenames:
            return codec.id
    # COLMAP dense matrices deliberately share the compound
    # ``.<photometric|geometric>.bin`` suffix. Their canonical workspace
    # parent directory is the unambiguous discriminator.
    if p.name.endswith((".photometric.bin", ".geometric.bin")):
        dense_parent_formats = {
            "depth_maps": "colmap_mvs_depth",
            "normal_maps": "colmap_mvs_normal",
            "consistency_graphs": "colmap_mvs_consistency",
        }
        for parent in p.parents:
            if parent.name in dense_parent_formats:
                return dense_parent_formats[parent.name]
    ext = p.suffix.lower()
    # PLY schemas share both suffix and magic; classify before registry order.
    if ext == ".ply":
        try:
            return classify_ply(p)
        except (OSError, ValueError) as exc:
            raise format_error(f"cannot classify PLY {str(path)!r}: {exc}") from exc
    if ext in {".h5", ".hdf5"} and any(
        codec.id in {"hdf5", "hloc_features", "hloc_matches"}
        for codec in ordered
    ):
        try:
            classified = classify_hdf5(p)
        except (OSError, ValueError) as exc:
            raise format_error(
                f"cannot classify HDF5 {str(path)!r}: {exc}"
            ) from exc
        if any(codec.id == classified for codec in ordered):
            return classified
    if (
        ext == ".webp"
        and any(codec.id == "animated_webp" for codec in ordered)
        and _is_animated_webp(p)
    ):
        return "animated_webp"
    if ext in {".avif", ".avifs"} and any(
        codec.id in {"avif", "animated_avif"} for codec in ordered
    ):
        brand = _avif_brand(p)
        if brand == "avis" and any(
            codec.id == "animated_avif" for codec in ordered
        ):
            return "animated_avif"
        if brand == "avif" and any(codec.id == "avif" for codec in ordered):
            return "avif"
    if (
        ext == ".png"
        and any(codec.id == "apng" for codec in ordered)
        and _is_apng(p)
    ):
        return "apng"
    for codec in ordered:
        if ext in codec.extensions:
            return codec.id
    try:
        with p.open("rb") as stream:
            # Byte 104 distinguishes extensionless LAS and LAZ.
            head = stream.read(105)
    except OSError:
        head = b""
    if head.startswith(b"ply"):
        try:
            return classify_ply(p)
        except (OSError, ValueError) as exc:
            raise format_error(f"cannot classify PLY {str(path)!r}: {exc}") from exc
    if head.startswith(b"LASF") and len(head) >= 105:
        encoded_format = head[104]
        if encoded_format & 0x80 and not encoded_format & 0x40:
            return "laz"
        return "las"
    if (
        head.startswith(b"RIFF")
        and len(head) >= 12
        and head[8:12] == b"WEBP"
    ):
        if (
            any(codec.id == "animated_webp" for codec in ordered)
            and _is_animated_webp(p)
        ):
            return "animated_webp"
        if any(codec.id == "webp" for codec in ordered):
            return "webp"
    if _could_be_isobmff(head) and any(
        codec.id in {"avif", "animated_avif"} for codec in ordered
    ):
        brand = _avif_brand(p)
        if brand == "avis" and any(
            codec.id == "animated_avif" for codec in ordered
        ):
            return "animated_avif"
        if brand == "avif" and any(codec.id == "avif" for codec in ordered):
            return "avif"
    if (
        head.startswith(b"\x89PNG\r\n\x1a\n")
        and any(codec.id == "apng" for codec in ordered)
        and _is_apng(p)
    ):
        return "apng"
    for codec in ordered:
        if any(head.startswith(magic) for magic in codec.magic):
            return codec.id
    raise format_error(f"cannot detect a format for {str(path)!r} (ext {ext!r})")
