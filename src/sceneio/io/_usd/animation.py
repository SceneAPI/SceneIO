"""Bounded selected-time evaluation for directly authored USDA node samples.

TinyUSDZ 0.9.4 exposes authored matrix sample times but not their typed
values, and does not expose authored visibility samples at all.  This module
parses only the provider-normalized, directly authored prim text needed by the
``sceneio.usd.3dcv/1`` selected-time profile.  It is deliberately not a
general USDA parser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

_MAX_PRIM_TEXT_CHARS = 256 * 1024 * 1024
_MAX_LINE_CHARS = 64 * 1024 * 1024
_MAX_SAMPLES_PER_PROPERTY = 65_536
_MAX_TOKENS_PER_PROPERTY = 2_000_000
_MAX_STRING_CHARS = 256
_NUMBER = re.compile(
    r"[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))"
    r"(?:[eE][+-]?[0-9]+)?"
)
_IDENTIFIER_START = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_"
)
_IDENTIFIER_CONTINUE = _IDENTIFIER_START | frozenset("0123456789")
_PROPERTY_CONTINUE = _IDENTIFIER_CONTINUE | frozenset(":")
_QUALIFIERS = frozenset({"custom", "uniform"})
_SUPPORTED_PROPERTIES = frozenset(
    {"visibility", "xformOp:transform"}
)
_VISIBILITY = frozenset({"inherited", "invisible"})
_XFORM_ORDERS = {
    ("xformOp:transform",): False,
    ("!resetXformStack!", "xformOp:transform"): True,
}


@dataclass(frozen=True)
class _Declaration:
    type_name: str
    name: str
    time_samples: bool
    value_start: int


@dataclass(frozen=True)
class SampledMatrices:
    """One validated, ordered matrix sample table."""

    times: np.ndarray
    values: np.ndarray


@dataclass(frozen=True)
class SampledTokens:
    """One validated, ordered held-token sample table."""

    times: np.ndarray
    values: tuple[str, ...]


@dataclass(frozen=True)
class ParsedPrimSamples:
    """The accepted sampled subset authored directly on one prim."""

    sampled_properties: frozenset[str]
    transform: SampledMatrices | None = None
    transform_resets_stack: bool = False
    visibility: SampledTokens | None = None

    @property
    def sample_count(self) -> int:
        """Return the number of authored property samples."""

        return (
            (0 if self.transform is None else len(self.transform.times))
            + (0 if self.visibility is None else len(self.visibility.times))
        )

    @property
    def sample_times(self) -> np.ndarray:
        """Return the ordered union of authored time codes."""

        tables = []
        if self.transform is not None:
            tables.append(self.transform.times)
        if self.visibility is not None:
            tables.append(self.visibility.times)
        if not tables:
            return np.empty(0, dtype=np.float64)
        return np.unique(np.concatenate(tables))


@dataclass(frozen=True)
class SelectedPrimValues:
    """Values materialized at one requested USD time code."""

    transform: np.ndarray | None = None
    transform_resets_stack: bool = False
    visibility: str | None = None


def _skip_horizontal(value: str, position: int) -> int:
    while position < len(value) and value[position] in " \t":
        position += 1
    return position


def _identifier(
    value: str,
    position: int,
    *,
    property_name: bool = False,
) -> tuple[str, int] | None:
    if position >= len(value) or value[position] not in _IDENTIFIER_START:
        return None
    allowed = _PROPERTY_CONTINUE if property_name else _IDENTIFIER_CONTINUE
    end = position + 1
    while end < len(value) and value[end] in allowed:
        end += 1
    return value[position:end], end


def _declaration_from_line(
    line: str,
    *,
    absolute_start: int,
) -> _Declaration | None:
    # Provider-normalized direct properties are exactly one indentation level
    # beneath the prim. Child properties therefore cannot be mistaken for the
    # current prim's declarations.
    if not line.startswith("    ") or (
        len(line) > 4 and line[4] in " \t"
    ):
        return None
    position = 4
    parsed = _identifier(line, position)
    if parsed is None:
        return None
    word, position = parsed
    while word in _QUALIFIERS:
        next_position = _skip_horizontal(line, position)
        if next_position == position:
            return None
        parsed = _identifier(line, next_position)
        if parsed is None:
            return None
        word, position = parsed
    type_name = word
    if line[position : position + 2] == "[]":
        type_name += "[]"
        position += 2
    next_position = _skip_horizontal(line, position)
    if next_position == position:
        return None
    parsed = _identifier(line, next_position, property_name=True)
    if parsed is None:
        return None
    name, position = parsed
    time_samples = line.startswith(".timeSamples", position)
    if time_samples:
        position += len(".timeSamples")
    position = _skip_horizontal(line, position)
    if position >= len(line) or line[position] != "=":
        return None
    position = _skip_horizontal(line, position + 1)
    return _Declaration(
        type_name=type_name,
        name=name,
        time_samples=time_samples,
        value_start=absolute_start + position,
    )


def _direct_declarations(text: str, *, context: str) -> tuple[_Declaration, ...]:
    if len(text) > _MAX_PRIM_TEXT_CHARS:
        raise ValueError(
            f"{context}: normalized prim text exceeds the selected-time limit"
        )
    declarations: list[_Declaration] = []
    position = 0
    while position < len(text):
        end = text.find("\n", position)
        if end < 0:
            end = len(text)
        if end - position > _MAX_LINE_CHARS:
            raise ValueError(
                f"{context}: normalized USDA line exceeds the selected-time "
                "limit"
            )
        line = text[position:end]
        if line.endswith("\r"):
            line = line[:-1]
        declaration = _declaration_from_line(
            line,
            absolute_start=position,
        )
        if declaration is not None:
            declarations.append(declaration)
        position = end + 1
    return tuple(declarations)


class _Cursor:
    def __init__(self, text: str, position: int, *, context: str) -> None:
        self.text = text
        self.position = position
        self.context = context
        self.tokens = 0

    def _token(self) -> None:
        self.tokens += 1
        if self.tokens > _MAX_TOKENS_PER_PROPERTY:
            raise ValueError(
                f"{self.context}: selected-time token limit exceeded"
            )

    def skip_space(self) -> None:
        while (
            self.position < len(self.text)
            and self.text[self.position].isspace()
        ):
            self.position += 1

    def peek(self) -> str | None:
        self.skip_space()
        if self.position >= len(self.text):
            return None
        return self.text[self.position]

    def consume(self, value: str) -> bool:
        self.skip_space()
        if not self.text.startswith(value, self.position):
            return False
        self.position += len(value)
        self._token()
        return True

    def expect(self, value: str) -> None:
        if not self.consume(value):
            raise ValueError(
                f"{self.context}: expected {value!r} in selected-time value"
            )

    def number(self) -> float:
        self.skip_space()
        match = _NUMBER.match(self.text, self.position)
        if match is None:
            raise ValueError(
                f"{self.context}: expected a finite numeric value"
            )
        self.position = match.end()
        self._token()
        value = float(match.group(0))
        if not np.isfinite(value):
            raise ValueError(
                f"{self.context}: selected-time numbers must be finite"
            )
        return value

    def string(self) -> str:
        self.skip_space()
        if self.position >= len(self.text) or self.text[self.position] != '"':
            raise ValueError(f"{self.context}: expected a quoted token")
        self.position += 1
        start = self.position
        while self.position < len(self.text):
            value = self.text[self.position]
            if value == '"':
                result = self.text[start : self.position]
                self.position += 1
                self._token()
                if len(result) > _MAX_STRING_CHARS:
                    raise ValueError(
                        f"{self.context}: selected-time token is too long"
                    )
                return result
            if value == "\\" or ord(value) < 32:
                raise ValueError(
                    f"{self.context}: escaped/control token text is outside "
                    "the selected-time grammar"
                )
            self.position += 1
        raise ValueError(f"{self.context}: unterminated quoted token")

    def require_line_end(self) -> None:
        while self.position < len(self.text):
            value = self.text[self.position]
            if value in " \t\r":
                self.position += 1
                continue
            if value == "\n":
                return
            raise ValueError(
                f"{self.context}: trailing data after selected-time value"
            )


def _matrix(cursor: _Cursor) -> np.ndarray:
    cursor.expect("(")
    rows: list[list[float]] = []
    for row_index in range(4):
        if row_index:
            cursor.expect(",")
        cursor.expect("(")
        row: list[float] = []
        for column in range(4):
            if column:
                cursor.expect(",")
            row.append(cursor.number())
        cursor.expect(")")
        rows.append(row)
    cursor.expect(")")
    result = np.asarray(rows, dtype=np.float64)
    if result.shape != (4, 4) or not np.isfinite(result).all():
        raise ValueError(f"{cursor.context}: invalid sampled matrix")
    return result


def _sample_map(
    cursor: _Cursor,
    value_parser,
) -> tuple[np.ndarray, list[object]]:
    cursor.expect("{")
    by_time: dict[float, object] = {}
    while True:
        if cursor.peek() == "}":
            cursor.expect("}")
            break
        time = cursor.number()
        cursor.expect(":")
        if time in by_time:
            raise ValueError(
                f"{cursor.context}: duplicate sample time {time!r}"
            )
        by_time[time] = value_parser(cursor)
        if len(by_time) > _MAX_SAMPLES_PER_PROPERTY:
            raise ValueError(
                f"{cursor.context}: selected-time sample limit exceeded"
            )
        if cursor.consume(","):
            continue
        if cursor.peek() != "}":
            raise ValueError(
                f"{cursor.context}: expected ',' or '}}' after sample"
            )
    cursor.require_line_end()
    if not by_time:
        raise ValueError(
            f"{cursor.context}: selected-time sample map must not be empty"
        )
    times = np.asarray(sorted(by_time), dtype=np.float64)
    return times, [by_time[float(time)] for time in times]


def _token_array(cursor: _Cursor) -> tuple[str, ...]:
    cursor.expect("[")
    values: list[str] = []
    if cursor.peek() != "]":
        while True:
            values.append(cursor.string())
            if cursor.consume(","):
                continue
            break
    cursor.expect("]")
    cursor.require_line_end()
    return tuple(values)


def sampled_property_names(text: str, *, context: str) -> frozenset[str]:
    """Return direct time-sampled property names without parsing bulk values."""

    # Static prim text is the overwhelmingly common inspection path.  Avoid
    # constructing a declaration table for large mesh/point array payloads
    # when the one token that can introduce authored samples is absent.
    if ".timeSamples" not in text:
        return frozenset()
    return frozenset(
        declaration.name
        for declaration in _direct_declarations(text, context=context)
        if declaration.time_samples
    )


def parse_prim_samples(text: str, *, path: str) -> ParsedPrimSamples:
    """Parse and validate the selected-time subset on one normalized prim."""

    context = f"USD prim {path!r}"
    declarations = _direct_declarations(text, context=context)
    sampled = frozenset(
        declaration.name
        for declaration in declarations
        if declaration.time_samples
    )
    unsupported = sorted(sampled - _SUPPORTED_PROPERTIES)
    if unsupported:
        raise ValueError(
            f"{context}: time-varying properties are outside the "
            "selected-time profile: " + ", ".join(unsupported)
        )
    sampled_declarations = {
        name: [
            declaration
            for declaration in declarations
            if declaration.time_samples and declaration.name == name
        ]
        for name in sampled
    }
    for name, matches in sampled_declarations.items():
        if len(matches) != 1:
            raise ValueError(
                f"{context}: duplicate timeSamples declaration for {name!r}"
            )

    transform = None
    resets = False
    if "xformOp:transform" in sampled:
        declaration = sampled_declarations["xformOp:transform"][0]
        if declaration.type_name != "matrix4d":
            raise ValueError(
                f"{context}: sampled xformOp:transform must have type matrix4d"
            )
        xform_names = {
            declaration.name
            for declaration in declarations
            if declaration.name == "xformOpOrder"
            or declaration.name.startswith("xformOp:")
        }
        if xform_names - {"xformOp:transform", "xformOpOrder"}:
            raise ValueError(
                f"{context}: sampled transforms require a single matrix "
                "xformOp stack"
            )
        order_declarations = [
            declaration
            for declaration in declarations
            if not declaration.time_samples
            and declaration.name == "xformOpOrder"
        ]
        if len(order_declarations) != 1:
            raise ValueError(
                f"{context}: sampled transform requires one static "
                "xformOpOrder"
            )
        order_declaration = order_declarations[0]
        if order_declaration.type_name != "token[]":
            raise ValueError(
                f"{context}: xformOpOrder must have type token[]"
            )
        order = _token_array(
            _Cursor(
                text,
                order_declaration.value_start,
                context=f"{context} xformOpOrder",
            )
        )
        try:
            resets = _XFORM_ORDERS[order]
        except KeyError:
            raise ValueError(
                f"{context}: selected-time xformOpOrder is outside the "
                "single-matrix profile"
            ) from None
        times, values = _sample_map(
            _Cursor(
                text,
                declaration.value_start,
                context=f"{context} xformOp:transform.timeSamples",
            ),
            _matrix,
        )
        transform = SampledMatrices(
            times=times,
            values=np.asarray(values, dtype=np.float64),
        )

    visibility = None
    if "visibility" in sampled:
        declaration = sampled_declarations["visibility"][0]
        if declaration.type_name != "token":
            raise ValueError(
                f"{context}: sampled visibility must have type token"
            )
        times, raw_values = _sample_map(
            _Cursor(
                text,
                declaration.value_start,
                context=f"{context} visibility.timeSamples",
            ),
            lambda cursor: cursor.string(),
        )
        values = tuple(str(value) for value in raw_values)
        invalid = sorted(set(values) - _VISIBILITY)
        if invalid:
            raise ValueError(
                f"{context}: unsupported sampled visibility values: "
                + ", ".join(repr(value) for value in invalid)
            )
        visibility = SampledTokens(times=times, values=values)

    return ParsedPrimSamples(
        sampled_properties=sampled,
        transform=transform,
        transform_resets_stack=resets,
        visibility=visibility,
    )


def _matrix_at(samples: SampledMatrices, time: float) -> np.ndarray:
    index = int(np.searchsorted(samples.times, time, side="left"))
    if index == 0:
        return np.array(samples.values[0], copy=True, order="C")
    if index == len(samples.times):
        return np.array(samples.values[-1], copy=True, order="C")
    if samples.times[index] == time:
        return np.array(samples.values[index], copy=True, order="C")
    lower = index - 1
    alpha = (time - samples.times[lower]) / (
        samples.times[index] - samples.times[lower]
    )
    # OpenUSD linearly interpolates matrix-valued attributes component-wise.
    return np.asarray(
        samples.values[lower]
        + alpha * (samples.values[index] - samples.values[lower]),
        dtype=np.float64,
        order="C",
    )


def _token_at(samples: SampledTokens, time: float) -> str:
    index = int(np.searchsorted(samples.times, time, side="right")) - 1
    index = min(max(index, 0), len(samples.times) - 1)
    return samples.values[index]


def evaluate_prim_samples(
    samples: ParsedPrimSamples,
    *,
    time: float,
) -> SelectedPrimValues:
    """Evaluate accepted node samples using OpenUSD-compatible semantics."""

    return SelectedPrimValues(
        transform=(
            None if samples.transform is None else _matrix_at(samples.transform, time)
        ),
        transform_resets_stack=samples.transform_resets_stack,
        visibility=(
            None
            if samples.visibility is None
            else _token_at(samples.visibility, time)
        ),
    )


__all__ = [
    "ParsedPrimSamples",
    "SelectedPrimValues",
    "evaluate_prim_samples",
    "parse_prim_samples",
    "sampled_property_names",
]
