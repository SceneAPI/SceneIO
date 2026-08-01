"""CLI for the generated USD material/asset benchmark."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.io_bench.usd_materials import render_results, run_benchmark


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--faces", type=int, default=100_000)
    parser.add_argument("--materials", type=int, default=8)
    parser.add_argument("--texture-mb", type=int, default=100)
    parser.add_argument(
        "--only",
        action="append",
        choices=("usda", "usdz"),
        dest="encodings",
    )
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    if args.faces < 0:
        parser.error("--faces must be nonnegative")
    if args.materials < 1:
        parser.error("--materials must be positive")
    if args.texture_mb < 0:
        parser.error("--texture-mb must be nonnegative")

    with TemporaryDirectory(prefix="sceneio_usd_material_bench_") as directory:
        results = run_benchmark(
            directory,
            runs=args.runs,
            face_count=args.faces,
            material_count=args.materials,
            texture_bytes=args.texture_mb * 1024 * 1024,
            encodings=tuple(args.encodings or ("usda", "usdz")),
        )
    rendered = render_results(results)
    print(rendered)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
