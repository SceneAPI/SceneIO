"""Exercise SceneIO native owners, records, sinks, and failures before LSan."""

from __future__ import annotations

import ctypes
import gc
import tempfile
from pathlib import Path

import numpy as np

import sceneio
from sceneio import _core


def _exercise_native_lifetimes() -> None:
    values = np.arange(4 * 8, dtype=np.int32).reshape(4, 8)
    encoded = bytes(_core.write_npy(values))
    np.testing.assert_array_equal(_core.read_npy(encoded), values)

    with tempfile.TemporaryDirectory(prefix="sceneio-lsan-") as directory:
        root = Path(directory)

        source_path = root / "source.npy"
        source_path.write_bytes(encoded)
        mapped = sceneio.read(source_path, format="npy")
        derived = mapped[1:, 2:]
        del mapped
        gc.collect()
        source_path.unlink()
        np.testing.assert_array_equal(derived, values[1:, 2:])
        del derived

        sink_path = root / "sink.npy"
        sceneio.write(values, sink_path, format="npy")
        assert sink_path.read_bytes() == encoded
        np.testing.assert_array_equal(sceneio.read(sink_path), values)

        malformed_path = root / "malformed.npy"
        malformed_path.write_bytes(encoded[:16])
        try:
            sceneio.read(malformed_path, format="npy")
        except sceneio.FormatError:
            pass
        else:
            raise AssertionError("truncated NPY unexpectedly decoded")
        malformed_path.unlink()

        cloud = _core.point_cloud(
            np.arange(18, dtype=np.float32).reshape(6, 3)
        )
        positions = cloud.positions
        del cloud
        gc.collect()
        assert positions.shape == (6, 3)
        assert float(positions[-1, -1]) == 17.0
        del positions


def _recoverable_leak_check() -> int:
    leak_check = ctypes.CDLL(None).__lsan_do_recoverable_leak_check
    leak_check.restype = ctypes.c_int
    return int(leak_check())


def main() -> int:
    _exercise_native_lifetimes()
    gc.collect()
    leaks = _recoverable_leak_check()
    if leaks:
        raise RuntimeError("LSan reported a leak after SceneIO lifetime checks")
    print("SceneIO LSan lifetime shard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
