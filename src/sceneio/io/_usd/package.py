"""USDZ container and atomic destination helpers."""

from __future__ import annotations

import hashlib
import json
import mmap
import os
import shutil
import struct
import tempfile
import unicodedata
import zipfile
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO

_USDZ_SOURCE_PREFIX = "sceneio-usdz:"
_COPY_CHUNK_SIZE = 1024 * 1024


def root_layer_prefix(path: str | os.PathLike[str]) -> bytes:
    """Return the first ten bytes of a direct layer or first USDZ entry."""

    with open(path, "rb") as source:
        prefix = source.read(10)
    if not prefix.startswith(b"PK\x03\x04"):
        return prefix
    try:
        with zipfile.ZipFile(path) as archive:
            entries, _ = _validated_archive_entries(archive)
            if not entries:
                return b""
            with archive.open(entries[0]) as root_layer:
                return root_layer.read(10)
    except (OSError, RuntimeError, zipfile.BadZipFile):
        return b""


def iter_root_layer_chunks(
    path: str | os.PathLike[str],
    *,
    chunk_size: int = 1024 * 1024,
):
    """Yield a direct layer or first USDZ entry without a whole-layer copy."""

    if chunk_size <= 0:
        raise ValueError("USD: root-layer chunk size must be positive")
    with open(path, "rb") as source:
        prefix = source.read(4)
    if not prefix.startswith(b"PK\x03\x04"):
        with open(path, "rb") as source:
            while chunk := source.read(chunk_size):
                yield chunk
        return
    with zipfile.ZipFile(path) as archive:
        entries, _ = _validated_archive_entries(archive)
        if not entries:
            return
        with archive.open(entries[0]) as root_layer:
            while chunk := root_layer.read(chunk_size):
                yield chunk


@contextmanager
def mapped_root_layer(path: str | os.PathLike[str]):
    """Map a direct layer or stored USDZ root as ``(map, start, end)``."""

    with open(path, "rb") as source:
        mapped = None
        try:
            size = source.seek(0, os.SEEK_END)
            source.seek(0)
            if not size:
                yield None
                return
            mapped = mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ)
            if not mapped[:4].startswith(b"PK\x03\x04"):
                yield mapped, 0, size
                return
            with zipfile.ZipFile(path) as archive:
                entries, _ = _validated_archive_entries(archive)
                if not entries:
                    yield None
                    return
                info = entries[0]
                if info.compress_type != zipfile.ZIP_STORED:
                    mapped.close()
                    mapped = None
                    with tempfile.TemporaryFile() as extracted:
                        with archive.open(info) as root_layer:
                            shutil.copyfileobj(
                                root_layer,
                                extracted,
                                length=1024 * 1024,
                            )
                        extracted_size = extracted.tell()
                        if not extracted_size:
                            yield None
                            return
                        extracted.flush()
                        extracted_map = mmap.mmap(
                            extracted.fileno(),
                            0,
                            access=mmap.ACCESS_READ,
                        )
                        try:
                            yield extracted_map, 0, extracted_size
                        finally:
                            extracted_map.close()
                    return
                header = info.header_offset
                if mapped[header : header + 4] != b"PK\x03\x04":
                    raise ValueError("USDZ: invalid root local-file header")
                name_length, extra_length = struct.unpack_from(
                    "<HH", mapped, header + 26
                )
                start = header + 30 + name_length + extra_length
                end = start + info.file_size
                if end > size:
                    raise ValueError("USDZ: root layer exceeds the archive")
                yield mapped, start, end
        finally:
            if mapped is not None:
                mapped.close()


def temporary_path(destination: Path, suffix: str) -> Path:
    """Create a sibling temporary path suitable for atomic replacement."""

    fd, name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=suffix,
        dir=destination.parent,
    )
    os.close(fd)
    return Path(name)


def normalize_asset_uri(uri: str, *, context: str = "USD asset") -> str:
    """Validate one portable, local, package-relative asset path."""

    if not isinstance(uri, str) or not uri:
        raise ValueError(f"{context}: path must be a non-empty string")
    if unicodedata.normalize("NFC", uri) != uri:
        raise ValueError(f"{context}: path must use NFC Unicode normalization")
    if "\x00" in uri or "\\" in uri or "@" in uri or "[" in uri or "]" in uri:
        raise ValueError(
            f"{context}: path must use forward slashes and contain no NUL"
        )
    if uri.startswith("/") or "://" in uri or "?" in uri or "#" in uri:
        raise ValueError(f"{context}: path must be local and relative")
    path = PurePosixPath(uri)
    if (
        str(path) != uri
        or any(part in {"", ".", ".."} for part in path.parts)
        or (path.parts and ":" in path.parts[0])
    ):
        raise ValueError(
            f"{context}: path must be normalized and may not escape its layer"
        )
    return uri


def _validated_archive_entries(
    archive: zipfile.ZipFile,
) -> tuple[list[zipfile.ZipInfo], dict[str, zipfile.ZipInfo]]:
    entries = archive.infolist()
    by_name: dict[str, zipfile.ZipInfo] = {}
    folded: dict[str, str] = {}
    for info in entries:
        if info.is_dir():
            raise ValueError("USDZ: directory entries are outside the profile")
        name = normalize_asset_uri(info.filename, context="USDZ package entry")
        if name in by_name:
            raise ValueError(f"USDZ: duplicate package entry {name!r}")
        key = name.casefold()
        if key in folded:
            raise ValueError(
                f"USDZ: package entries {folded[key]!r} and {name!r} "
                "are not portable together"
            )
        if info.flag_bits & 0x1:
            raise ValueError(f"USDZ: encrypted package entry {name!r}")
        by_name[name] = info
        folded[key] = name
    return entries, by_name


def validate_usdz_input(path: str | os.PathLike[str]) -> None:
    """Require stored, portable, 64-byte-aligned USDZ package members."""

    candidate = Path(path)
    try:
        with candidate.open("rb") as source:
            if not source.read(4).startswith(b"PK\x03\x04"):
                return
        with zipfile.ZipFile(candidate) as archive:
            entries, _ = _validated_archive_entries(archive)
            if not entries:
                raise ValueError("USDZ: package has no root layer")
            compressed = [
                info.filename
                for info in entries
                if info.compress_type != zipfile.ZIP_STORED
            ]
            if compressed:
                raise ValueError(
                    "USDZ: package entries must be stored, not compressed: "
                    + ", ".join(compressed)
                )
            with candidate.open("rb") as raw:
                for info in entries:
                    raw.seek(info.header_offset)
                    header = raw.read(30)
                    if len(header) != 30 or header[:4] != b"PK\x03\x04":
                        raise ValueError(
                            f"USDZ: invalid local header for {info.filename!r}"
                        )
                    method = struct.unpack_from("<H", header, 8)[0]
                    name_length, extra_length = struct.unpack_from(
                        "<HH", header, 26
                    )
                    encoded_name = raw.read(name_length)
                    encoding = "utf-8" if info.flag_bits & 0x800 else "cp437"
                    try:
                        local_name = encoded_name.decode(encoding)
                    except UnicodeDecodeError:
                        raise ValueError(
                            "USDZ: local package names must use their declared "
                            "encoding"
                        ) from None
                    if local_name != info.filename or method != info.compress_type:
                        raise ValueError(
                            f"USDZ: local and central entries disagree for "
                            f"{info.filename!r}"
                        )
                    data_offset = (
                        info.header_offset
                        + 30
                        + name_length
                        + extra_length
                    )
                    if data_offset % 64:
                        raise ValueError(
                            f"USDZ: package entry {info.filename!r} is not "
                            "64-byte aligned"
                        )
    except zipfile.BadZipFile as exc:
        raise ValueError(f"USDZ: invalid package: {exc}") from exc


def _resolved_relative_file(root: Path, uri: str, *, context: str) -> Path:
    try:
        resolved_root = root.resolve(strict=True)
        source = resolved_root.joinpath(
            *PurePosixPath(uri).parts
        ).resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{context}: source file is missing: {exc}") from exc
    try:
        source.relative_to(resolved_root)
    except ValueError:
        raise ValueError(
            f"{context}: resolved path leaves the root-layer directory"
        ) from None
    if not source.is_file():
        raise ValueError(f"{context}: source is not a file")
    return source


def _package_source(archive: Path, member: str) -> str:
    return _USDZ_SOURCE_PREFIX + json.dumps(
        [str(archive.resolve()), member],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _parse_package_source(source: str) -> tuple[Path, str] | None:
    if not source.startswith(_USDZ_SOURCE_PREFIX):
        return None
    try:
        value = json.loads(source[len(_USDZ_SOURCE_PREFIX) :])
    except (json.JSONDecodeError, TypeError):
        raise ValueError("USD asset source: invalid USDZ locator") from None
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise ValueError("USD asset source: invalid USDZ locator")
    member = normalize_asset_uri(value[1], context="USDZ asset source")
    return Path(value[0]), member


def asset_source_for(
    stage_path: str | os.PathLike[str],
    uri: str,
) -> str:
    """Resolve one authored texture URI without loading its bytes."""

    normalized = normalize_asset_uri(uri, context="USD texture")
    stage = Path(stage_path).resolve()
    try:
        with stage.open("rb") as source:
            packaged_stage = source.read(4).startswith(b"PK\x03\x04")
    except OSError as exc:
        raise ValueError(f"USD stage {str(stage)!r} is unavailable: {exc}") from exc
    if packaged_stage:
        try:
            with zipfile.ZipFile(stage) as archive:
                entries, by_name = _validated_archive_entries(archive)
                if not entries:
                    raise ValueError("USDZ: package has no root layer")
                root_parent = PurePosixPath(entries[0].filename).parent
                member = str(root_parent / PurePosixPath(normalized))
                member = normalize_asset_uri(
                    member,
                    context="USDZ texture",
                )
                try:
                    info = by_name[member]
                except KeyError:
                    raise ValueError(
                        f"USDZ texture {normalized!r}: package entry is missing"
                    ) from None
                if info.is_dir():
                    raise ValueError(
                        f"USDZ texture {normalized!r}: entry is a directory"
                    )
                if info.compress_type != zipfile.ZIP_STORED:
                    raise ValueError(
                        f"USDZ texture {normalized!r}: entry must be stored"
                    )
        except zipfile.BadZipFile as exc:
            raise ValueError(f"USDZ: invalid package: {exc}") from exc
        return _package_source(stage, member)

    source = _resolved_relative_file(
        stage.parent,
        normalized,
        context=f"USD texture {normalized!r}",
    )
    return str(source)


@contextmanager
def open_asset_source(
    source: str,
    *,
    relative_to: Path | None = None,
):
    """Open one direct or package-contained asset locator for streaming."""

    packaged = _parse_package_source(source)
    if packaged is not None:
        archive_path, member = packaged
        try:
            with zipfile.ZipFile(archive_path) as archive:
                try:
                    _, by_name = _validated_archive_entries(archive)
                    info = by_name[member]
                except KeyError:
                    raise ValueError(
                        f"USDZ asset source {member!r}: entry is missing"
                    ) from None
                if info.is_dir() or info.compress_type != zipfile.ZIP_STORED:
                    raise ValueError(
                        f"USDZ asset source {member!r}: entry must be a stored file"
                    )
                with archive.open(info) as stream:
                    yield stream
        except (OSError, zipfile.BadZipFile) as exc:
            raise ValueError(
                f"USDZ asset source {str(archive_path)!r} is unavailable: {exc}"
            ) from exc
        return

    path = Path(source)
    if not path.is_absolute():
        if relative_to is None:
            raise ValueError(
                f"USD asset source {source!r} is relative without a base"
            )
        path = relative_to.joinpath(path)
    try:
        with path.open("rb") as stream:
            yield stream
    except OSError as exc:
        raise ValueError(
            f"USD asset source {str(path)!r} is unavailable: {exc}"
        ) from exc


def validate_unpacked_asset_sources(
    destination: Path,
    assets: Iterable[tuple[str, str]],
) -> None:
    """Require unpackaged URIs to name their exact recorded local sources."""

    root = destination.parent
    for uri, source_locator in assets:
        normalized = normalize_asset_uri(uri, context="USD texture")
        expected = _resolved_relative_file(
            root,
            normalized,
            context=f"USD texture {normalized!r}",
        )
        if _parse_package_source(source_locator) is not None:
            raise ValueError(
                f"USD texture {normalized!r}: a USDZ source cannot be "
                "written unpackaged"
            )
        recorded = Path(source_locator)
        if not recorded.is_absolute():
            recorded = root / recorded
        try:
            recorded = recorded.resolve(strict=True)
        except OSError as exc:
            raise ValueError(
                f"USD texture {normalized!r}: recorded source is missing: {exc}"
            ) from exc
        if not recorded.is_file() or not os.path.samefile(expected, recorded):
            raise ValueError(
                f"USD texture {normalized!r}: package_assets=False requires "
                "the recorded source to be the destination-relative file"
            )


def _copy_and_hash(source: str, output: BinaryIO, *, relative_to: Path) -> bytes:
    digest = hashlib.sha256()
    with open_asset_source(source, relative_to=relative_to) as input_stream:
        while chunk := input_stream.read(_COPY_CHUNK_SIZE):
            output.write(chunk)
            digest.update(chunk)
    return digest.digest()


def _hash_path(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_COPY_CHUNK_SIZE):
            digest.update(chunk)
    return digest.digest()


def _asset_filename(index: int, uri: str) -> str:
    suffix = PurePosixPath(uri).suffix.lower()
    return f"texture_{index:04d}{suffix}"


@contextmanager
def prepared_sidecar_assets(
    destination: Path,
    assets: Iterable[tuple[str, str]],
):
    """Install an immutable content-addressed sidecar directory transactionally."""

    values = list(assets)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}.assets.",
            dir=destination.parent,
        )
    )
    installed: Path | None = None
    mapping: dict[str, str] = {}
    manifest = hashlib.sha256()
    try:
        for index, (uri, source) in enumerate(values):
            normalized = normalize_asset_uri(uri, context="USD texture")
            if normalized in mapping:
                raise ValueError(
                    f"USD texture {normalized!r}: duplicate external asset"
                )
            name = _asset_filename(index, normalized)
            output = temporary / name
            with output.open("wb") as stream:
                digest = _copy_and_hash(
                    source,
                    stream,
                    relative_to=destination.parent,
                )
            manifest.update(normalized.encode("utf-8"))
            manifest.update(b"\0")
            manifest.update(digest)
            mapping[normalized] = name
        directory_name = (
            f"{destination.stem}.assets-{manifest.hexdigest()[:16]}"
        )
        final_directory = destination.parent / directory_name
        if final_directory.exists():
            if not final_directory.is_dir():
                raise ValueError(
                    f"USD asset destination {str(final_directory)!r} "
                    "is not a directory"
                )
            expected = sorted(mapping.values())
            entries = list(final_directory.iterdir())
            if any(not item.is_file() for item in entries):
                raise ValueError(
                    f"USD asset destination {str(final_directory)!r} "
                    "contains non-file entries"
                )
            actual = sorted(item.name for item in entries)
            if actual != expected:
                raise ValueError(
                    f"USD asset destination {str(final_directory)!r} "
                    "does not match the prepared asset set"
                )
            for name in expected:
                left = _hash_path(temporary / name)
                right = _hash_path(final_directory / name)
                if left != right:
                    raise ValueError(
                        f"USD asset destination {str(final_directory)!r} "
                        "contains different bytes"
                    )
        else:
            os.replace(temporary, final_directory)
            installed = final_directory
        yield {
            uri: f"{directory_name}/{name}"
            for uri, name in mapping.items()
        }
    except Exception:
        if installed is not None:
            shutil.rmtree(installed, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _aligned_info(archive: zipfile.ZipFile, name: str, size: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.file_size = size
    base = archive.fp.tell() + 30 + len(name.encode("utf-8")) + 4
    padding = (-base) % 64
    info.extra = struct.pack("<HH", 0xFFFF, padding) + bytes(padding)
    return info


def _stream_entry(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    input_stream: BinaryIO,
) -> None:
    with archive.open(
        info,
        mode="w",
        force_zip64=info.file_size >= 0xFFFFFFFF,
    ) as output_stream:
        shutil.copyfileobj(
            input_stream,
            output_stream,
            length=_COPY_CHUNK_SIZE,
        )


def write_usdz_archive(
    source: Path,
    destination: Path,
    *,
    assets: Iterable[tuple[str, str]] = (),
) -> None:
    """Store a root USDA layer and texture assets with 64-byte alignment."""

    with zipfile.ZipFile(
        destination,
        mode="w",
        compression=zipfile.ZIP_STORED,
        allowZip64=True,
    ) as archive:
        name = "root.usda"
        info = _aligned_info(archive, name, source.stat().st_size)
        with source.open("rb") as input_stream:
            _stream_entry(archive, info, input_stream)
        seen = {name}
        for arcname, source_locator in assets:
            normalized = normalize_asset_uri(
                arcname,
                context="USDZ output asset",
            )
            if normalized in seen:
                raise ValueError(
                    f"USDZ output asset {normalized!r} is duplicated"
                )
            seen.add(normalized)
            with open_asset_source(
                source_locator,
                relative_to=destination.parent,
            ) as input_stream, tempfile.TemporaryFile() as staged:
                shutil.copyfileobj(
                    input_stream,
                    staged,
                    length=_COPY_CHUNK_SIZE,
                )
                size = staged.tell()
                staged.seek(0)
                _stream_entry(
                    archive,
                    _aligned_info(archive, normalized, size),
                    staged,
                )


__all__ = [
    "asset_source_for",
    "iter_root_layer_chunks",
    "mapped_root_layer",
    "normalize_asset_uri",
    "open_asset_source",
    "prepared_sidecar_assets",
    "root_layer_prefix",
    "temporary_path",
    "validate_unpacked_asset_sources",
    "validate_usdz_input",
    "write_usdz_archive",
]
