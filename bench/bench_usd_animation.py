"""CLI wrapper for the generated USD selected-time benchmark."""

from __future__ import annotations

import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.io_bench.usd_animation import main  # noqa: I001


if __name__ == "__main__":
    raise SystemExit(main())
