"""Command-line entry point for the SceneIO I/O benchmark."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

main = importlib.import_module("bench.io_bench.runner").main


if __name__ == "__main__":
    main()
