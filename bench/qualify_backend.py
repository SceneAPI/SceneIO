"""CLI facade for installed-wheel backend qualification."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

main = importlib.import_module(
    "bench.io_bench.backend_qualification.runner"
).main


if __name__ == "__main__":
    raise SystemExit(main())
