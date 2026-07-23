"""Private ndarray subtype for safely exporting read-only mapped arrays."""

from __future__ import annotations

import numpy as np


class _MappedArray(np.ndarray):
    """A mapped view whose DLPack export is an isolated C-contiguous copy."""

    def __dlpack__(
        self,
        *,
        stream=None,
        max_version=None,
        dl_device=None,
        copy=None,
    ):
        if copy is False:
            raise BufferError("a mapped read-only array cannot provide writable DLPack aliasing")
        owned = np.array(self, copy=True, order="C", subok=False)
        kwargs = {"stream": stream}
        if max_version is not None:
            kwargs["max_version"] = max_version
        if dl_device is not None:
            kwargs["dl_device"] = dl_device
        try:
            return owned.__dlpack__(**kwargs)
        except TypeError:
            if max_version is not None or dl_device is not None:
                raise
            # NumPy 1.26 predates the version/device protocol keywords.
            return owned.__dlpack__(stream=stream)
