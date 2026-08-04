"""Bounded YAML subset used by ASL-style ``sensor.yaml`` files.

The base package intentionally does not depend on a general YAML runtime. This
parser accepts only mappings, scalar values, inline scalar lists, and the
``!!opencv-matrix`` mapping tag used by the public dataset profile.
"""

from __future__ import annotations

import ast
import math
import re
from pathlib import Path

_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_LIMIT = 1024 * 1024


def _strip_comment(value: str) -> str:
    quote: str | None = None
    escaped = False
    bracket_depth = 0
    for index, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if quote is not None:
            if character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "[":
            bracket_depth += 1
        elif character == "]":
            bracket_depth -= 1
            if bracket_depth < 0:
                raise ValueError("sensor YAML contains an unmatched closing bracket")
        elif character == "#" and bracket_depth == 0:
            return value[:index]
    if quote is not None or bracket_depth != 0:
        raise ValueError("sensor YAML contains an unterminated quote or list")
    return value


def _separator(value: str, token: str) -> int:
    quote: str | None = None
    escaped = False
    depth = 0
    for index, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if quote is not None:
            if character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
        elif character == token and depth == 0:
            return index
    return -1


def _list_items(value: str) -> list[str]:
    body = value[1:-1].strip()
    if not body:
        return []
    items: list[str] = []
    begin = 0
    while begin < len(body):
        offset = _separator(body[begin:], ",")
        if offset < 0:
            token = body[begin:].strip()
            begin = len(body)
        else:
            token = body[begin : begin + offset].strip()
            begin += offset + 1
        if not token:
            raise ValueError("sensor YAML inline lists cannot contain empty items")
        items.append(token)
    return items


def _scalar(value: str) -> object:
    if value.startswith("["):
        if not value.endswith("]"):
            raise ValueError("sensor YAML inline list is unterminated")
        return [_scalar(item) for item in _list_items(value)]
    if value.startswith(("'", '"')):
        try:
            decoded = ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:
            raise ValueError("sensor YAML contains an invalid quoted string") from exc
        if not isinstance(decoded, str):
            raise ValueError("sensor YAML quoted values must be strings")
        return decoded
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "~"}:
        return None
    try:
        integer = int(value, 10)
    except ValueError:
        try:
            number = float(value)
        except ValueError:
            if any(character in value for character in "{}&*|>!"):
                raise ValueError(
                    "sensor YAML value uses an unsupported construct"
                ) from None
            return value
        if not math.isfinite(number):
            raise ValueError("sensor YAML numeric values must be finite") from None
        return number
    return integer


def parse_sensor_yaml(path: Path) -> dict[str, object]:
    """Parse one regular UTF-8 sensor document under the bounded profile."""

    if path.is_symlink() or not path.is_file():
        raise ValueError(f"euroc_dataset: {path.name!r} must be a regular file")
    size = path.stat().st_size
    if size > _LIMIT:
        raise ValueError("euroc_dataset: sensor YAML exceeds 1 MiB")
    payload = path.read_bytes()
    if len(payload) != size:
        raise ValueError("euroc_dataset: sensor YAML changed while being read")
    if b"\0" in payload:
        raise ValueError("euroc_dataset: sensor YAML contains a NUL byte")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("euroc_dataset: sensor YAML must be UTF-8") from exc

    document: dict[str, object] = {}
    stack: list[tuple[int, dict[str, object]]] = [(-1, document)]
    previous_indent = -1
    previous_nested = True
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        if "\t" in raw_line[: len(raw_line) - len(raw_line.lstrip())]:
            raise ValueError(
                f"euroc_dataset: sensor YAML line {line_number} uses tab indentation"
            )
        line = _strip_comment(raw_line).rstrip()
        if not line.strip() or line.lstrip().startswith(("%YAML", "---", "...")):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent > previous_indent and previous_indent >= 0 and not previous_nested:
            raise ValueError(
                f"euroc_dataset: unexpected indentation on YAML line {line_number}"
            )
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        content = line[indent:]
        colon = _separator(content, ":")
        if colon <= 0:
            raise ValueError(
                f"euroc_dataset: YAML line {line_number} must be a key/value mapping"
            )
        key = content[:colon].strip()
        if _KEY.fullmatch(key) is None:
            raise ValueError(
                f"euroc_dataset: YAML line {line_number} has an invalid key"
            )
        parent = stack[-1][1]
        if key in parent:
            raise ValueError(f"euroc_dataset: duplicate YAML key {key!r}")
        encoded = content[colon + 1 :].strip()
        if not encoded or encoded == "!!opencv-matrix":
            child: dict[str, object] = {}
            parent[key] = child
            stack.append((indent, child))
            previous_nested = True
        else:
            parent[key] = _scalar(encoded)
            previous_nested = False
        previous_indent = indent
    if not document:
        raise ValueError("euroc_dataset: sensor YAML is empty")
    return document


__all__ = ["parse_sensor_yaml"]
