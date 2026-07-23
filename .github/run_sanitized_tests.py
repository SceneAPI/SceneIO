"""Run pytest and ask LSan for leaks before CPython's shutdown teardown."""

from __future__ import annotations

import ctypes
import gc
import sys

import pytest


def main() -> int:
    test_status = int(pytest.main(sys.argv[1:]))
    gc.collect()

    # CPython and extension modules retain process-lifetime registries that are
    # dismantled after main returns. Checking here avoids those shutdown-only
    # false positives without suppressing allocator or capsule stack frames.
    leak_check = ctypes.CDLL(None).__lsan_do_recoverable_leak_check
    leak_check.restype = ctypes.c_int
    leaks = leak_check()
    if leaks:
        print("LeakSanitizer reported test-lifetime leaks.", file=sys.stderr)
    return test_status or int(bool(leaks))


if __name__ == "__main__":
    raise SystemExit(main())
