"""CLI for the generated rich-USD geometry benchmark."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.io_bench.usd_scene import render_results, run_benchmark


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--faces", type=int, default=100_000)
    parser.add_argument("--points", type=int, default=100_000)
    parser.add_argument(
        "--only",
        action="append",
        choices=("usda", "usdz"),
        dest="encodings",
    )
    parser.add_argument("--cold-cache", action="store_true")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    if args.faces < 0 or args.points < 0:
        parser.error("--faces and --points must be nonnegative")

    with TemporaryDirectory(prefix="sceneio_usd_bench_") as directory:
        results = run_benchmark(
            directory,
            runs=args.runs,
            face_count=args.faces,
            point_count=args.points,
            encodings=tuple(args.encodings or ("usda", "usdz")),
            cold_cache=args.cold_cache,
        )
    rendered = render_results(results)
    print(rendered)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
