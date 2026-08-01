"""CLI for the generated USD volume and point-instancer benchmark."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.io_bench.usd_payloads import render_results, run_benchmark


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--instances", type=int, action="append", dest="counts")
    parser.add_argument("--vdb-mib", type=int, default=1024)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    counts = tuple(args.counts or (1_000_000,))
    if args.runs < 1:
        parser.error("--runs must be positive")
    if any(count < 1 for count in counts):
        parser.error("--instances must be positive")
    if args.vdb_mib < 1:
        parser.error("--vdb-mib must be positive")

    with TemporaryDirectory(prefix="sceneio_usd_payload_bench_") as directory:
        results = run_benchmark(
            directory,
            runs=args.runs,
            instance_counts=counts,
            vdb_size_mib=args.vdb_mib,
        )
    rendered = render_results(results)
    print(rendered)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
