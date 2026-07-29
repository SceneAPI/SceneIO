"""Ordered format detection independent of the registry facade."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from sceneio.io._registry.model import Codec


def detect_path(
    path,
    codecs: Iterable[Codec],
    *,
    classify_ply: Callable[[Path], str],
    format_error: Callable[[str], Exception],
) -> str:
    """Detect ``path`` using the supplied canonical codec order."""

    p = Path(path)
    ordered = tuple(codecs)
    if p.is_dir():
        for codec in ordered:
            if codec.is_directory and (p / codec.dir_marker).exists():
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
    for codec in ordered:
        if any(head.startswith(magic) for magic in codec.magic):
            return codec.id
    raise format_error(f"cannot detect a format for {str(path)!r} (ext {ext!r})")
