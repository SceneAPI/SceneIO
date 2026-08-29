"""Run one off-by-default LSan allocation control in an isolated process."""

from __future__ import annotations

import argparse
import ctypes
import gc

from sceneio import _native_test


def _recoverable_leak_check() -> int:
    leak_check = ctypes.CDLL(None).__lsan_do_recoverable_leak_check
    leak_check.restype = ctypes.c_int
    return int(leak_check())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("clean", "leak"))
    args = parser.parse_args()

    if args.mode == "clean":
        _native_test.allocate_clean()
    else:
        _native_test.allocate_leak()
    gc.collect()

    leaks = _recoverable_leak_check()
    print(f"LSan {args.mode} control result: {leaks}")
    return int(bool(leaks))


if __name__ == "__main__":
    raise SystemExit(main())
