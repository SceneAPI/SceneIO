"""Small primitives shared by independent metadata-inspector families."""

from __future__ import annotations

import mmap
from pathlib import Path


def _compiled_buffer_inspect(path: Path, function):
    with path.open("rb") as stream:
        try:
            mapped = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        except (OSError, ValueError):
            stream.seek(0)
            return function(stream.read())
        with mapped:
            return function(mapped)
