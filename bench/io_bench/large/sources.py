"""Pinned source acquisition for the large-file I/O benchmark.

The benchmark never stores upstream media in the repository.  This module
loads the checked-in provenance manifest, streams selected assets into a
caller-provided cache, and verifies the recorded byte count and SHA-256 before
returning a path to a caller.  The public functions intentionally keep the
surface small so benchmark case adapters can share the same source contract.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_MANIFEST = _REPOSITORY_ROOT / "bench" / "data" / "large_io_sources.toml"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_CONTENT_REVISION_RE = re.compile(r"^content-sha256:[0-9a-f]{64}$")
_SOURCE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class SourceIntegrityError(ValueError):
    """Raised when a cached/downloaded source differs from its manifest."""


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """Immutable provenance and integrity metadata for one upstream asset."""

    id: str
    use: str
    repository: str
    revision: str
    revision_type: str
    source_path: str
    url: str
    filename: str
    license: str
    license_url: str
    attribution: str
    expected_size_bytes: int
    expected_sha256: str
    media_type: str
    acquisition: str
    derivation: str
    sceneio_direct_supported: bool
    sceneio_direct_reason: str


@dataclass(frozen=True, slots=True)
class AcquiredSource:
    """A verified source path plus the immutable metadata that selected it."""

    spec: SourceSpec
    path: Path
    size_bytes: int
    sha256: str


def _manifest_path(manifest_path: str | Path | None) -> Path:
    path = _DEFAULT_MANIFEST if manifest_path is None else Path(manifest_path)
    if not path.is_file():
        raise FileNotFoundError(f"large I/O source manifest not found: {path}")
    return path


def _text_field(row: Mapping[str, object], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"source field {name!r} must be a non-empty string")
    return value


def _validate_spec(row: Mapping[str, object]) -> SourceSpec:
    required = {
        "id",
        "use",
        "repository",
        "revision",
        "revision_type",
        "source_path",
        "url",
        "filename",
        "license",
        "license_url",
        "attribution",
        "expected_size_bytes",
        "expected_sha256",
        "media_type",
        "acquisition",
        "derivation",
        "sceneio_direct_supported",
        "sceneio_direct_reason",
    }
    missing = sorted(required.difference(row))
    if missing:
        raise ValueError(f"source row is missing fields: {', '.join(missing)}")

    values = {
        name: _text_field(row, name)
        for name in required
        - {"expected_size_bytes", "sceneio_direct_supported"}
    }
    source_id = values["id"]
    if not _SOURCE_ID_RE.fullmatch(source_id):
        raise ValueError(f"invalid source id {source_id!r}")
    filename = values["filename"]
    if Path(filename).name != filename or filename in {"", ".", ".."}:
        raise ValueError(f"source filename must be a plain file name: {filename!r}")
    if not values["url"].startswith("https://"):
        raise ValueError(f"source URL must use HTTPS: {values['url']!r}")
    revision = values["revision"]
    if not (_GIT_COMMIT_RE.fullmatch(revision) or _CONTENT_REVISION_RE.fullmatch(revision)):
        raise ValueError(f"source revision is not immutable: {revision!r}")
    expected_size = row["expected_size_bytes"]
    if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size <= 0:
        raise ValueError("expected_size_bytes must be a positive integer")
    expected_sha256 = values["expected_sha256"]
    if not _SHA256_RE.fullmatch(expected_sha256):
        raise ValueError(f"expected_sha256 is not a lowercase SHA-256 digest: {expected_sha256!r}")
    sceneio_direct_supported = row["sceneio_direct_supported"]
    if not isinstance(sceneio_direct_supported, bool):
        raise ValueError("sceneio_direct_supported must be a boolean")
    return SourceSpec(
        expected_size_bytes=expected_size,
        sceneio_direct_supported=sceneio_direct_supported,
        **values,
    )


def load_sources(manifest_path: str | Path | None = None) -> Mapping[str, SourceSpec]:
    """Load and validate the immutable source catalog.

    The returned mapping is a read-only snapshot.  A custom manifest path is
    useful to local benchmark harnesses and tests; production callers use the
    checked-in manifest by leaving it unset.
    """

    path = _manifest_path(manifest_path)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("large I/O source manifest schema_version must be 1")
    rows = data.get("source")
    if not isinstance(rows, list) or not rows:
        raise ValueError("large I/O source manifest must contain source rows")
    specs: dict[str, SourceSpec] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each large I/O source row must be a TOML table")
        spec = _validate_spec(row)
        if spec.id in specs:
            raise ValueError(f"duplicate large I/O source id: {spec.id}")
        specs[spec.id] = spec
    return MappingProxyType(specs)


def _selected_specs(only: Iterable[str] | None) -> tuple[SourceSpec, ...]:
    specs = load_sources()
    if only is None:
        selected_ids = tuple(specs)
    elif isinstance(only, str):
        selected_ids = (only,)
    else:
        selected_ids = tuple(only)
    unknown = sorted(set(selected_ids).difference(specs))
    if unknown:
        raise KeyError(f"unknown large I/O source id(s): {', '.join(unknown)}")
    selected = set(selected_ids)
    return tuple(spec for spec in specs.values() if spec.id in selected)


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _verify_path(spec: SourceSpec, path: Path) -> AcquiredSource:
    if not path.is_file():
        raise FileNotFoundError(f"cached source is missing for {spec.id}: {path}")
    size_bytes, sha256 = _sha256_file(path)
    if size_bytes != spec.expected_size_bytes or sha256 != spec.expected_sha256:
        raise SourceIntegrityError(
            f"cached source does not match manifest for {spec.id}: "
            f"size={size_bytes} (expected {spec.expected_size_bytes}), "
            f"sha256={sha256} (expected {spec.expected_sha256})"
        )
    return AcquiredSource(spec=spec, path=path, size_bytes=size_bytes, sha256=sha256)


def _download_to(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": "SceneIO-large-io/1.0"})
    try:
        with urlopen(request, timeout=180) as response, destination.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"unable to download large I/O source from {url}") from exc


def _cache_path(cache: Path, spec: SourceSpec) -> Path:
    # SourceSpec validation guarantees filename cannot escape this directory.
    return cache / spec.id / spec.filename


def acquire_sources(
    cache: Path, only: Iterable[str] | None = None
) -> Mapping[str, AcquiredSource]:
    """Download selected sources into ``cache`` and verify every result."""

    cache = Path(cache).expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    acquired: dict[str, AcquiredSource] = {}
    for spec in _selected_specs(only):
        destination = _cache_path(cache, spec)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file():
            try:
                acquired[spec.id] = _verify_path(spec, destination)
                continue
            except SourceIntegrityError:
                pass
        temporary = destination.with_name(f".{destination.name}.part")
        try:
            _download_to(spec.url, temporary)
            acquired[spec.id] = _verify_path(spec, temporary)
            temporary.replace(destination)
            acquired[spec.id] = _verify_path(spec, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
    return MappingProxyType(acquired)


def verify_sources(
    cache: Path, only: Iterable[str] | None = None
) -> Mapping[str, AcquiredSource]:
    """Verify selected cached sources without making any network request."""

    cache = Path(cache).expanduser().resolve()
    verified: dict[str, AcquiredSource] = {}
    for spec in _selected_specs(only):
        verified[spec.id] = _verify_path(spec, _cache_path(cache, spec))
    return MappingProxyType(verified)


__all__ = [
    "AcquiredSource",
    "SourceIntegrityError",
    "SourceSpec",
    "acquire_sources",
    "load_sources",
    "verify_sources",
]
