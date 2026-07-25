"""Repeat the controlled default LAZperf check through the native module."""

from __future__ import annotations

from sceneio import _native_test


def main() -> int:
    assert _native_test.lazperf_default_corrector_rejects()
    print("SceneIO default LAZperf corrector guard passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
