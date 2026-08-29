"""Shared helpers for standard NCore V4 component profiles."""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence

import numpy as np

from sceneio.io._ncore.model import NCoreComponentData, NCoreGroup


def mapping(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{context} must be an object")
    if any(not isinstance(name, str) for name in value):
        raise ValueError(f"{context} keys must be strings")
    return value


def sequence(value: object, context: str) -> Sequence[object]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{context} must be an array")
    return value


def non_empty_string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value or value.isspace():
        raise ValueError(f"{context} must be a non-empty string")
    return value


def integer(value: object, context: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{context} must be an integer >= {minimum}")
    return value


def finite_number(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{context} must be a finite number")
    return result


def numeric_vector(
    value: object,
    length: int | None,
    context: str,
) -> np.ndarray:
    raw = sequence(value, context)
    if length is not None and len(raw) != length:
        raise ValueError(f"{context} must contain {length} values")
    result = np.array(
        [finite_number(item, f"{context}[{index}]") for index, item in enumerate(raw)],
        dtype=np.float64,
    )
    result.setflags(write=False)
    return result


def groups(data: NCoreComponentData) -> Mapping[str, NCoreGroup]:
    return {group.name: group for group in data.groups}


def require_group(data: NCoreComponentData, name: str) -> NCoreGroup:
    try:
        return groups(data)[name]
    except KeyError:
        raise ValueError(
            f"NCore {data.component.id} requires group {name!r}"
        ) from None


def child_group_names(data: NCoreComponentData, parent: str) -> tuple[str, ...]:
    prefix = f"{parent}/"
    return tuple(
        name[len(prefix) :]
        for name in sorted(groups(data))
        if name.startswith(prefix) and "/" not in name[len(prefix) :]
    )


def arrays_below(
    data: NCoreComponentData,
    prefix: str,
) -> dict[str, np.ndarray]:
    normalized = prefix.rstrip("/") + "/"
    return {
        name[len(normalized) :]: value
        for name, value in data.arrays.items()
        if name.startswith(normalized)
    }


def array_attributes(
    data: NCoreComponentData, relative_name: str
) -> Mapping[str, object]:
    for descriptor in data.component.arrays:
        if descriptor.name == relative_name:
            return descriptor.attributes
    raise ValueError(
        f"NCore {data.component.id} has no array descriptor {relative_name!r}"
    )


def require_version(data: NCoreComponentData) -> None:
    if data.component.version != "v1":
        raise ValueError(
            f"NCore standard component {data.component.id} supports version 'v1', "
            f"got {data.component.version!r}"
        )


def validate_sequence_timestamp(
    value: int,
    interval: tuple[int, int],
    context: str,
) -> None:
    if not interval[0] <= value < interval[1]:
        raise ValueError(f"{context} lies outside the sequence interval")


def frame_intervals(
    data: NCoreComponentData,
    sequence_interval_us: tuple[int, int],
) -> tuple[tuple[str, tuple[int, int]], ...]:
    raw = require_group(data, "frames").attributes.get("frames_timestamps_us")
    values = sequence(raw, f"NCore {data.component.id} frame timestamps")
    intervals: list[tuple[str, tuple[int, int]]] = []
    for index, raw_interval in enumerate(values):
        pair = sequence(
            raw_interval,
            f"NCore {data.component.id} frame interval {index}",
        )
        if len(pair) != 2:
            raise ValueError("NCore sensor frame intervals require start/stop")
        start = integer(pair[0], "NCore sensor frame start")
        stop = integer(pair[1], "NCore sensor frame stop")
        if stop < start or stop > np.iinfo(np.uint64).max:
            raise ValueError("NCore sensor frame interval is invalid")
        if not (
            sequence_interval_us[0] <= start < sequence_interval_us[1]
            and sequence_interval_us[0] <= stop < sequence_interval_us[1]
        ):
            raise ValueError("NCore sensor frame lies outside the sequence interval")
        intervals.append((str(stop), (start, stop)))
    if any(
        left[1][0] >= right[1][0] or left[1][1] >= right[1][1]
        for left, right in itertools.pairwise(intervals)
    ):
        raise ValueError("NCore sensor frame timestamps must be increasing")
    selected = set(data.selected_items)
    has_selection = (
        data.selection.frames is not None
        or data.selection.timestamps_us is not None
    )
    if has_selection:
        intervals = [item for item in intervals if item[0] in selected]
    return tuple(intervals)


__all__ = [
    "array_attributes",
    "arrays_below",
    "child_group_names",
    "finite_number",
    "frame_intervals",
    "groups",
    "integer",
    "mapping",
    "non_empty_string",
    "numeric_vector",
    "require_group",
    "require_version",
    "sequence",
    "validate_sequence_timestamp",
]
