"""Stable CLI facade for the large-file benchmark."""

from __future__ import annotations

import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.io_bench.large.runner import main

if __name__ == "__main__":  # pragma: no cover - command-line entry point
    raise SystemExit(main())


__all__ = ["main"]
