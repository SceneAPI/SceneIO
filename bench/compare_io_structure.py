"""Compare deterministic I/O benchmark structure with a checked contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _is_diagnostic_key(key: str, benchmark_contract: dict) -> bool:
    return key.endswith(
        tuple(benchmark_contract["excluded_key_suffixes"])
    ) or any(
        fragment in key
        for fragment in benchmark_contract["excluded_key_substrings"]
    )


def _project_value(
    value,
    *,
    codec: str,
    path: str,
    benchmark_contract: dict,
):
    if isinstance(value, dict):
        projected = {}
        for key, item in value.items():
            if _is_diagnostic_key(key, benchmark_contract):
                continue
            item_path = f"{path}.{key}" if path else f"{codec}.{key}"
            if item_path in benchmark_contract["tolerated_traced_paths"]:
                projected[key] = benchmark_contract["tolerance_sentinel"]
            else:
                projected[key] = _project_value(
                    item,
                    codec=codec,
                    path=item_path,
                    benchmark_contract=benchmark_contract,
                )
        return projected
    if isinstance(value, list):
        return [
            _project_value(
                item,
                codec=codec,
                path=path,
                benchmark_contract=benchmark_contract,
            )
            for item in value
        ]
    return value


def structural_projection(rows: list[dict], benchmark_contract: dict) -> list[dict]:
    """Remove diagnostic metrics and normalize predeclared traced jitter."""

    return [
        _project_value(
            row,
            codec=row["codec"],
            path="",
            benchmark_contract=benchmark_contract,
        )
        for row in rows
    ]


def projection_sha256(rows: list[dict], benchmark_contract: dict) -> str:
    payload = json.dumps(
        structural_projection(rows, benchmark_contract),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _value_at_path(rows: list[dict], dotted_path: str):
    codec, *keys = dotted_path.split(".")
    value = next(row for row in rows if row["codec"] == codec)
    for key in keys:
        value = value[key]
    return value


def validate(rows: list[dict], contract: dict) -> None:
    benchmark_contract = contract["benchmark_parent"]
    if len(rows) != benchmark_contract["rows"]:
        raise ValueError(
            f"benchmark row count {len(rows)} differs from "
            f"{benchmark_contract['rows']}"
        )

    for path, tolerance in benchmark_contract[
        "tolerated_traced_paths"
    ].items():
        candidate = _value_at_path(rows, path)
        nearest_delta_bytes = min(
            abs(candidate - parent) * 1_000_000
            for parent in tolerance["parent_values"]
        )
        if nearest_delta_bytes > tolerance["maximum_delta_bytes"]:
            raise ValueError(
                f"{path} differs from its nearest parent capture by "
                f"{nearest_delta_bytes:.0f} bytes"
            )

    actual_hash = projection_sha256(rows, benchmark_contract)
    expected_hash = benchmark_contract["structural_projection_sha256"]
    if actual_hash != expected_hash:
        raise ValueError(
            f"benchmark structure hash {actual_hash} differs from {expected_hash}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("tests/contracts/io_registry_assembly_v1.json"),
    )
    args = parser.parse_args()

    rows = json.loads(args.candidate.read_text(encoding="utf-8"))
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    validate(rows, contract)
    print(
        "I/O benchmark structure matches "
        f"{contract['benchmark_parent']['structural_projection_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
