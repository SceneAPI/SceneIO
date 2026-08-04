"""CLI for the generated dense-label NPZ/Zarr benchmark."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.io_bench.label_maps import run_benchmark


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--side", type=int, default=4096)
    parser.add_argument("--only", choices=("npz", "zarr"), action="append")
    parser.add_argument("--zarr-format", choices=(2, 3), type=int, default=3)
    parser.add_argument("--chunk-side", type=int, default=1024)
    parser.add_argument("--rss-samples", type=int, default=3)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    if args.side < 1:
        parser.error("--side must be positive")
    if args.chunk_side < 1:
        parser.error("--chunk-side must be positive")
    if args.rss_samples < 0:
        parser.error("--rss-samples must be nonnegative")
    carriers = tuple(dict.fromkeys(args.only or ("npz", "zarr")))
    with TemporaryDirectory(prefix="sceneio-label-map-bench-") as directory:
        results = run_benchmark(
            directory,
            side=args.side,
            runs=args.runs,
            carriers=carriers,
            zarr_format=args.zarr_format,
            chunk_side=args.chunk_side,
            rss_samples=args.rss_samples,
        )
    rendered = json.dumps(results, indent=2)
    print(rendered)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
