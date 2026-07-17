"""Content-addressed blob store contract.

`BlobStore` is the sha256-keyed binary-store Protocol every concrete
backend implements. It lives here, in the sceneapi-io contract package,
so backends and the sceneapi core agree on one interface: the core ships
the concrete `FSBlobStore` / `S3BlobStore` / `InMemoryBlobStore` stores
(and the `get_blob_store()` factory), while this module owns only the
protocol surface and the shared sha-format validator.

`validate_sha` is the canonical content-address format check
(``sha256`` lowercase hex, 64 chars). It raises :class:`SceneIoError` on
a malformed address; a bare ``SceneIoError`` maps to HTTP 507 in the
sceneapi core, matching the historic ``StorageError`` behaviour.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable

from sceneapi_io.errors import SceneIoError


@runtime_checkable
class BlobStore(Protocol):
    """Sha256-keyed binary store. All methods are sha-addressed; the
    backend chooses where bytes physically live."""

    def exists(self, sha: str) -> bool: ...

    def put_stream(self, reader: BinaryIO, *, chunk_size: int = ...) -> tuple[str, int]: ...

    def put_bytes(self, data: bytes) -> tuple[str, int]: ...

    def open(self, sha: str) -> BinaryIO: ...

    def aiter_chunks(self, sha: str, *, chunk_size: int = ...) -> AsyncIterator[bytes]: ...

    def delete(self, sha: str) -> None: ...

    def local_path(self, sha: str) -> Path:
        """Return a local filesystem path for the blob's bytes.

        For filesystem backends this is the canonical storage path.
        For remote backends (S3) the bytes are downloaded into the
        local cache on first access; subsequent calls return the
        cached path. Callers that need to hand a real path to a native
        library (pycolmap, Pillow, OpenCV) should use this.
        """
        ...


def validate_sha(sha: str) -> None:
    """Validate a content address is ``sha256`` lowercase hex (64 chars).

    Raises :class:`SceneIoError` on a malformed address.
    """
    if len(sha) != 64 or not all(c in "0123456789abcdef" for c in sha):
        raise SceneIoError(f"Invalid sha: {sha!r}")


# Backwards-compatible private alias so the sceneapi core (and any other
# importer) can keep the historic ``_validate_sha`` name.
_validate_sha = validate_sha
