# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# SPDX-License-Identifier: Apache-2.0

"""Direct-seek reader for NCore's Apache-2.0 indexed-tar layout.

NCore ``.itar`` files remain ordinary tar archives.  A compressed CBOR index
and a 20-byte header in the final 512-byte block add constant-time member
lookup.  This implementation is independent of NCore's Zarr-2 store class and
can be adapted to the Zarr-3 asynchronous Store API on demand.

The on-disk header/index constants and lookup algorithm are adapted from
NVIDIA NCore revision 12f4429522c98356c5a46eee1d84f29bd846e367. SceneIO's
implementation adds independent validation and targets Zarr 3.
"""

from __future__ import annotations

import lzma
import os
import struct
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

_BLOCK_SIZE = 512
_HEADER = struct.Struct("<4sIQI")
_MAGIC = b"itar"
_INDEX_CBOR_LZMA_XZ_V1 = 1
_DEFAULT_TAIL_SIZE = 1 << 20
_MAX_INDEX_DECODED_BYTES = 256 << 20
_MAX_RECORDS = 10_000_000


def _require_cbor2():
    try:
        import cbor2
    except ModuleNotFoundError:
        raise RuntimeError(
            "NCore indexed-tar support requires the optional dependency; "
            "install sceneio[ncore]"
        ) from None
    return cbor2


@dataclass(frozen=True, slots=True)
class IndexedTarRecord:
    """Physical payload range for one tar member."""

    offset: int
    size: int


class IndexedTarReader:
    """Read an NCore indexed tar through its trailing index."""

    def __init__(
        self,
        path: str | Path,
        *,
        tail_size: int = _DEFAULT_TAIL_SIZE,
    ) -> None:
        source = Path(path).resolve()
        if not source.is_file():
            raise ValueError("NCore indexed tar: expected a regular file")
        if isinstance(tail_size, bool) or not isinstance(tail_size, int):
            raise TypeError("NCore indexed tar: tail_size must be an integer")
        if tail_size < _BLOCK_SIZE:
            tail_size = _BLOCK_SIZE
        self.path = source
        self._stream = source.open("rb")
        self._lock = threading.RLock()
        self._closed = False
        try:
            self._records, self._tail_start, self._tail = self._load_index(
                tail_size
            )
        except BaseException:
            self._stream.close()
            self._closed = True
            raise

    def _load_index(
        self,
        tail_size: int,
    ) -> tuple[dict[str, IndexedTarRecord], int, bytes]:
        stream = self._stream
        stream.seek(0, os.SEEK_END)
        file_size = stream.tell()
        if file_size < _BLOCK_SIZE or file_size % _BLOCK_SIZE:
            raise ValueError(
                "NCore indexed tar: file size must end on a 512-byte block"
            )
        actual_tail_size = min(file_size, tail_size)
        tail_start = file_size - actual_tail_size
        stream.seek(tail_start)
        tail = stream.read(actual_tail_size)
        if len(tail) != actual_tail_size:
            raise ValueError("NCore indexed tar: short tail read")
        header_start = len(tail) - _BLOCK_SIZE
        magic, index_type, index_offset, index_size = _HEADER.unpack_from(
            tail, header_start
        )
        if magic != _MAGIC:
            raise ValueError("NCore indexed tar: invalid index header magic")
        if index_type != _INDEX_CBOR_LZMA_XZ_V1:
            raise ValueError(
                f"NCore indexed tar: unsupported index type {index_type}"
            )
        header_offset = file_size - _BLOCK_SIZE
        if (
            index_size <= 0
            or index_offset > header_offset
            or index_size > header_offset - index_offset
        ):
            raise ValueError("NCore indexed tar: index range is outside the file")
        if index_offset >= tail_start and index_offset + index_size <= file_size:
            start = index_offset - tail_start
            encoded = tail[start : start + index_size]
        else:
            stream.seek(index_offset)
            encoded = stream.read(index_size)
        if len(encoded) != index_size:
            raise ValueError("NCore indexed tar: short index read")
        decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
        try:
            decoded = decompressor.decompress(
                encoded,
                max_length=_MAX_INDEX_DECODED_BYTES + 1,
            )
        except lzma.LZMAError as exc:
            raise ValueError(f"NCore indexed tar: invalid compressed index: {exc}") from exc
        if len(decoded) > _MAX_INDEX_DECODED_BYTES or not decompressor.eof:
            raise ValueError("NCore indexed tar: decoded index exceeds the supported limit")
        try:
            table = _require_cbor2().loads(decoded)
        except Exception as exc:
            raise ValueError(f"NCore indexed tar: invalid CBOR index: {exc}") from exc
        if not isinstance(table, dict) or set(table) != {
            "items",
            "offset_datas",
            "sizes",
        }:
            raise ValueError("NCore indexed tar: index table has an invalid schema")
        items = table["items"]
        offsets = table["offset_datas"]
        sizes = table["sizes"]
        if not all(isinstance(values, (list, tuple)) for values in (items, offsets, sizes)):
            raise ValueError("NCore indexed tar: index columns must be arrays")
        if len(items) != len(offsets) or len(items) != len(sizes):
            raise ValueError("NCore indexed tar: index column lengths disagree")
        if len(items) > _MAX_RECORDS:
            raise ValueError("NCore indexed tar: record count exceeds the supported limit")
        records: dict[str, IndexedTarRecord] = {}
        for index, (key, offset, size) in enumerate(
            zip(items, offsets, sizes, strict=True)
        ):
            if not isinstance(key, str) or not key:
                raise ValueError(
                    f"NCore indexed tar: item {index} has an invalid key"
                )
            if key.startswith("/") or "\\" in key or any(
                part in {"", ".", ".."} for part in key.split("/")
            ):
                raise ValueError(
                    f"NCore indexed tar: item {index} key is not a relative path"
                )
            if key in records:
                raise ValueError(f"NCore indexed tar: duplicate key {key!r}")
            if (
                isinstance(offset, bool)
                or isinstance(size, bool)
                or not isinstance(offset, int)
                or not isinstance(size, int)
                or offset < 0
                or size < 0
                or offset > index_offset
                or size > index_offset - offset
            ):
                raise ValueError(
                    f"NCore indexed tar: item {index} has an invalid payload range"
                )
            records[key] = IndexedTarRecord(offset, size)
        return records, tail_start, tail

    @property
    def closed(self) -> bool:
        return self._closed

    def __enter__(self) -> IndexedTarReader:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._stream.close()
                self._closed = True

    def keys(self) -> tuple[str, ...]:
        return tuple(self._records)

    def __contains__(self, key: object) -> bool:
        return key in self._records

    def __iter__(self) -> Iterator[str]:
        return iter(self._records)

    def __len__(self) -> int:
        return len(self._records)

    def read(
        self,
        key: str,
        byte_range: tuple[int, int] | None = None,
    ) -> bytes:
        """Read one complete member or a half-open range within that member."""

        if self._closed:
            raise ValueError("NCore indexed tar: reader is closed")
        try:
            record = self._records[key]
        except KeyError:
            raise KeyError(key) from None
        start = 0
        stop = record.size
        if byte_range is not None:
            if not isinstance(byte_range, tuple) or len(byte_range) != 2:
                raise ValueError("NCore indexed tar: byte range must contain start/stop")
            start, stop = byte_range
            if (
                isinstance(start, bool)
                or isinstance(stop, bool)
                or not isinstance(start, int)
                or not isinstance(stop, int)
                or start < 0
                or stop < start
                or stop > record.size
            ):
                raise ValueError("NCore indexed tar: byte range is outside the member")
        absolute_start = record.offset + start
        size = stop - start
        tail_stop = self._tail_start + len(self._tail)
        if absolute_start >= self._tail_start and absolute_start + size <= tail_stop:
            relative = absolute_start - self._tail_start
            return self._tail[relative : relative + size]
        with self._lock:
            self._stream.seek(absolute_start)
            payload = self._stream.read(size)
        if len(payload) != size:
            raise ValueError(f"NCore indexed tar: short member read for {key!r}")
        return payload


def as_zarr_store(reader: IndexedTarReader):
    """Adapt an open reader to the optional Zarr 3 read-only Store API."""

    try:
        from zarr.abc.store import (
            OffsetByteRequest,
            RangeByteRequest,
            Store,
            SuffixByteRequest,
        )
    except ModuleNotFoundError:
        raise RuntimeError(
            "NCore support requires the optional dependency; install sceneio[ncore]"
        ) from None

    def normalize_request(size: int, request) -> tuple[int, int]:
        if request is None:
            return 0, size
        if isinstance(request, RangeByteRequest):
            start, stop = request.start, request.end
        elif isinstance(request, OffsetByteRequest):
            start, stop = request.offset, size
        elif isinstance(request, SuffixByteRequest):
            start, stop = max(0, size - request.suffix), size
        else:
            raise TypeError(f"unsupported Zarr byte request {type(request).__name__}")
        if start < 0 or stop < start or stop > size:
            raise ValueError("Zarr byte request is outside the indexed-tar member")
        return start, stop

    class _IndexedTarZarrStore(Store):
        def __init__(self) -> None:
            super().__init__(read_only=True)

        def __eq__(self, value: object) -> bool:
            return self is value

        @property
        def supports_writes(self) -> bool:
            return False

        @property
        def supports_deletes(self) -> bool:
            return False

        @property
        def supports_listing(self) -> bool:
            return True

        async def get(self, key, prototype, byte_range=None):
            record = reader._records.get(key)
            if record is None:
                return None
            interval = normalize_request(record.size, byte_range)
            return prototype.buffer.from_bytes(reader.read(key, interval))

        async def exists(self, key):
            return key in reader

        async def get_partial_values(self, prototype, key_ranges):
            return [
                await self.get(key, prototype, byte_range)
                for key, byte_range in key_ranges
            ]

        async def list(self):
            for key in reader:
                yield key

        async def list_prefix(self, prefix):
            for key in reader:
                if key.startswith(prefix):
                    yield key

        async def list_dir(self, prefix):
            normalized = prefix.rstrip("/")
            if normalized:
                marker = normalized + "/"
                values = {
                    key.removeprefix(marker).split("/", 1)[0]
                    for key in reader
                    if key.startswith(marker)
                }
            else:
                values = {key.split("/", 1)[0] for key in reader}
            for key in sorted(values):
                yield key

        async def set(self, key, value):
            self._check_writable()

        async def delete(self, key):
            self._check_writable()

    return _IndexedTarZarrStore()


__all__ = ["IndexedTarReader", "IndexedTarRecord", "as_zarr_store"]
