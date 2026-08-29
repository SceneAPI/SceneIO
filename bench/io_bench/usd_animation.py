"""Generated selected-time USD state-B benchmark.

The benchmark measures the accepted selected-time materialization and
inspection routes against an equal-node static control. Authored-animation
preservation and writing are intentionally absent because FC6 closes in state
B, not state A.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path

import numpy as np

import sceneio
from bench.io_bench.measure import (
    measure,
    measure_fresh_process_rss,
    measure_in_process_rss,
)
from bench.io_bench.memory_protocol import MemoryCase, MemoryOperation


def _matrix(node: int, sample: int) -> str:
    x = node * 0.125 + sample * 0.75
    y = node * -0.25 + sample * 0.5
    z = node % 17 + sample * 0.125
    return (
        f"((1,0,0,{x:.9g}),(0,1,0,{y:.9g}),"
        f"(0,0,1,{z:.9g}),(0,0,0,1))"
    )


def write_fixture(
    path: str | Path,
    *,
    node_count: int,
    samples_per_node: int,
    animated: bool,
) -> None:
    """Write one deterministic direct USDA node table."""

    if node_count < 1:
        raise ValueError("node_count must be positive")
    if samples_per_node < 1:
        raise ValueError("samples_per_node must be positive")
    destination = Path(path)
    with destination.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(
            '#usda 1.0\n(\n    upAxis = "Y"\n'
            "    startTimeCode = -3\n"
            f"    endTimeCode = {samples_per_node * 1.25:.9g}\n"
            "    timeCodesPerSecond = 30\n)\n"
        )
        for node in range(node_count):
            stream.write(f'def Xform "Node{node}"\n{{\n')
            if animated:
                stream.write("    token visibility.timeSamples = {\n")
                stream.write('        -3: "inherited",\n')
                stream.write('        0: "invisible",\n')
                stream.write('        4.5: "inherited"\n    }\n')
                stream.write(
                    "    matrix4d xformOp:transform.timeSamples = {\n"
                )
                for sample in range(samples_per_node):
                    time = -2.5 + sample * 1.25
                    comma = "," if sample + 1 < samples_per_node else ""
                    stream.write(
                        f"        {time:.9g}: {_matrix(node, sample)}"
                        f"{comma}\n"
                    )
                stream.write("    }\n")
            else:
                stream.write(
                    "    matrix4d xformOp:transform = "
                    f"{_matrix(node, samples_per_node // 2)}\n"
                )
            stream.write(
                '    uniform token[] xformOpOrder = '
                '["xformOp:transform"]\n}\n'
            )


def _metrics(operation, *, runs: int) -> dict[str, float]:
    elapsed, traced_peak = measure(operation, runs)
    rss_peak = measure_in_process_rss(operation)
    return {
        "ms": elapsed * 1000,
        "traced_peak_mb": traced_peak / 1e6,
        "rss_peak_mb": rss_peak / 1e6,
    }


def run_benchmark(
    directory: str | Path,
    *,
    runs: int = 3,
    node_count: int = 1_000,
    samples_per_node: int = 32,
    selected_time: float = 6.25,
    fresh_rss_samples: int = 0,
    fresh_rss_timeout_seconds: float = 60.0,
) -> dict[str, object]:
    """Measure selected-time read, inspection, and a static-node control."""

    if runs < 1:
        raise ValueError("runs must be positive")
    if not np.isfinite(selected_time):
        raise ValueError("selected_time must be finite")
    if fresh_rss_samples not in {0} and fresh_rss_samples < 3:
        raise ValueError("fresh_rss_samples must be zero or at least three")
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    animated = root / "selected-time.usda"
    static = root / "static-control.usda"
    write_fixture(
        animated,
        node_count=node_count,
        samples_per_node=samples_per_node,
        animated=True,
    )
    write_fixture(
        static,
        node_count=node_count,
        samples_per_node=samples_per_node,
        animated=False,
    )

    def selected_read():
        return sceneio.read_scene(
            animated,
            time=selected_time,
            load_payloads=False,
        )

    def inspect_animated():
        return sceneio.inspect(animated)

    def static_read():
        return sceneio.read_scene(static, load_payloads=False)

    selected = selected_read()
    inspected = inspect_animated()
    control = static_read()
    if len(selected.node_names) != node_count or len(control.node_names) != node_count:
        raise AssertionError("USD animation benchmark node count differs")
    if selected.selected_time != selected_time:
        raise AssertionError("USD animation benchmark selected time differs")
    expected_samples = node_count * (samples_per_node + 3)
    if inspected.metadata["sample_count"] != expected_samples:
        raise AssertionError("USD animation benchmark sample count differs")
    del selected, inspected, control

    metrics = {
        "selected_time_read": _metrics(selected_read, runs=runs),
        "inspect": _metrics(inspect_animated, runs=runs),
        "static_control_read": _metrics(static_read, runs=runs),
    }
    result = {
        "schema_version": "usd-selected-time-benchmark-v1",
        "fixture": {
            "node_count": node_count,
            "samples_per_node": samples_per_node,
            "authored_sample_count": expected_samples,
            "selected_time": selected_time,
            "animated_file_bytes": animated.stat().st_size,
            "static_file_bytes": static.stat().st_size,
        },
        "metrics": metrics,
        "close_state": "B_selected_time_read_only",
        "not_applicable": [
            "full_animation_preservation_read",
            "authored_animation_write",
        ],
    }
    if fresh_rss_samples:
        result["fresh_process_rss"] = measure_fresh_process_rss(
            [
                MemoryCase(
                    "selected_time_read",
                    animated.stat().st_size,
                    MemoryOperation(
                        "sceneio_read_scene",
                        {
                            "path": str(animated.resolve()),
                            "time": selected_time,
                            "load_payloads": False,
                        },
                    ),
                ),
                MemoryCase(
                    "inspect",
                    animated.stat().st_size,
                    MemoryOperation(
                        "sceneio_inspect",
                        {
                            "path": str(animated.resolve()),
                            "format": "usd",
                        },
                    ),
                ),
                MemoryCase(
                    "static_control_read",
                    static.stat().st_size,
                    MemoryOperation(
                        "sceneio_read_scene",
                        {
                            "path": str(static.resolve()),
                            "load_payloads": False,
                        },
                    ),
                ),
            ],
            samples=fresh_rss_samples,
            timeout_seconds=fresh_rss_timeout_seconds,
        )
    return result


def render_results(result: dict[str, object]) -> str:
    return json.dumps(result, indent=2, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("bench-out"))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--nodes", type=int, default=1_000)
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--time", type=float, default=6.25)
    parser.add_argument("--fresh-rss-samples", type=int, default=0)
    parser.add_argument(
        "--fresh-rss-timeout-seconds",
        type=float,
        default=60.0,
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = run_benchmark(
        args.directory,
        runs=args.runs,
        node_count=args.nodes,
        samples_per_node=args.samples,
        selected_time=args.time,
        fresh_rss_samples=args.fresh_rss_samples,
        fresh_rss_timeout_seconds=args.fresh_rss_timeout_seconds,
    )
    rendered = render_results(result)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    gc.collect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["render_results", "run_benchmark", "write_fixture"]
