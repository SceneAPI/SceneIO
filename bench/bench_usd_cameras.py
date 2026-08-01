"""CLI for the generated USD many-camera benchmark."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.io_bench.usd_cameras import render_results, run_benchmark


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--count", type=int, action="append", dest="counts")
    parser.add_argument(
        "--only",
        action="append",
        choices=("usda", "usdz"),
        dest="encodings",
    )
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    counts = tuple(args.counts or (10_000,))
    if args.runs < 1:
        parser.error("--runs must be positive")
    if any(count < 1 for count in counts):
        parser.error("--count must be positive")

    with TemporaryDirectory(prefix="sceneio_usd_camera_bench_") as directory:
        results = run_benchmark(
            directory,
            runs=args.runs,
            camera_counts=counts,
            encodings=tuple(args.encodings or ("usda", "usdz")),
        )
    rendered = render_results(results)
    print(rendered)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
