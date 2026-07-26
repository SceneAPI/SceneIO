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
            if key.endswith(
                tuple(benchmark_contract["normalized_value_suffixes"])
            ):
                if item is None:
                    projected[key] = None
                elif isinstance(item, (int, float)) and not isinstance(
                    item, bool
                ):
                    projected[key] = benchmark_contract[
                        "normalized_value_sentinel"
                    ]
                else:
                    raise TypeError(
                        f"{item_path} must be a numeric scalar or null"
                    )
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
    """Retain stable structure while normalizing runtime-dependent metrics."""

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


def validate(rows: list[dict], contract: dict) -> None:
    benchmark_contract = contract["benchmark_parent"]
    if len(rows) != benchmark_contract["rows"]:
        raise ValueError(
            f"benchmark row count {len(rows)} differs from "
            f"{benchmark_contract['rows']}"
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
