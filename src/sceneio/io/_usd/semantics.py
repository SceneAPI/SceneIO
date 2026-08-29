"""Bounded UsdSemanticsLabelsAPI mapping for SceneGraph nodes."""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Mapping

_API_PREFIX = "SemanticsLabelsAPI:"
_PROPERTY_PREFIX = "semantics:labels:"
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_DECLARATION = re.compile(
    r"^ {4}(?:(?:custom|uniform)\s+)*"
    r"(?P<type>[A-Za-z_][A-Za-z0-9_]*\[\]|"
    r"[A-Za-z_][A-Za-z0-9_]*)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_:.]*)\s*=",
    re.MULTILINE,
)


def _array_end(text: str, start: int, *, context: str) -> int:
    quoted = False
    escaped = False
    for index in range(start + 1, len(text)):
        character = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character == "]":
            return index
    raise ValueError(f"{context}: unterminated token array")


def semantic_properties(prim, *, text: str | None = None) -> frozenset[str]:
    """Return directly authored semantic-label properties."""

    if text is None:
        try:
            names = prim.property_names()
        except Exception:
            text = prim.to_string()
        else:
            return frozenset(
                name for name in names if name.startswith(_PROPERTY_PREFIX)
            )
    return frozenset(
        match.group("name")
        for match in _DECLARATION.finditer(text)
        if match.group("name").startswith(_PROPERTY_PREFIX)
    )


def _direct_labels(prim, *, text: str) -> dict[str, set[str]]:
    context = f"USD prim {prim.name!r} semantics"
    applied: list[str] = []
    for schema in prim.api_schemas():
        if not str(schema).startswith(_API_PREFIX):
            continue
        taxonomy = str(schema)[len(_API_PREFIX) :]
        if not _IDENTIFIER.fullmatch(taxonomy):
            raise ValueError(
                f"{context}: taxonomy {taxonomy!r} is not a portable identifier"
            )
        applied.append(taxonomy)
    if len(applied) != len(set(applied)):
        raise ValueError(f"{context}: duplicate taxonomy application")

    declarations = {
        match.group("name"): match
        for match in _DECLARATION.finditer(text)
        if match.group("name").startswith(_PROPERTY_PREFIX)
    }
    result: dict[str, set[str]] = {}
    for property_name, declaration in declarations.items():
        taxonomy = property_name[len(_PROPERTY_PREFIX) :]
        if taxonomy not in applied:
            raise ValueError(
                f"{context}: {property_name!r} requires {_API_PREFIX}{taxonomy}"
            )
        if declaration.group("type") != "token[]":
            raise ValueError(
                f"{context}: {property_name!r} must have type token[]"
            )
        start = declaration.end()
        while start < len(text) and text[start].isspace():
            start += 1
        if start >= len(text) or text[start] != "[":
            raise ValueError(
                f"{context}: {property_name!r} must be a static token array"
            )
        end = _array_end(text, start, context=context)
        try:
            values = ast.literal_eval(text[start : end + 1])
        except (SyntaxError, ValueError):
            raise ValueError(
                f"{context}: invalid token array in {property_name!r}"
            ) from None
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value for value in values
        ):
            raise ValueError(
                f"{context}: {property_name!r} labels must be non-empty tokens"
            )
        result[taxonomy] = set(values)
    return result


def inherited_pair(
    prim,
    inherited: Mapping[str, frozenset[str]],
    *,
    text: str | None = None,
) -> tuple[str, str, dict[str, frozenset[str]]]:
    """Compute the one representable inherited taxonomy/label pair."""

    if text is None:
        text = prim.to_string()
    combined = {name: set(values) for name, values in inherited.items()}
    for taxonomy, labels in _direct_labels(prim, text=text).items():
        combined.setdefault(taxonomy, set()).update(labels)
    nonempty = {name: labels for name, labels in combined.items() if labels}
    if len(nonempty) > 1:
        raise ValueError(
            f"USD prim {prim.name!r}: inherited semantics contain multiple "
            "taxonomies"
        )
    if nonempty:
        taxonomy, labels = next(iter(nonempty.items()))
        if len(labels) > 1:
            raise ValueError(
                f"USD prim {prim.name!r}: inherited semantics contain "
                "multiple labels"
            )
        label = next(iter(labels))
    else:
        taxonomy = label = ""
    return (
        taxonomy,
        label,
        {name: frozenset(values) for name, values in combined.items()},
    )


def validate_writable_semantics(scene, parents) -> tuple[bool, ...]:
    """Validate evaluated node labels and mark minimal authoring points."""

    taxonomies = tuple(scene.node_semantic_taxonomies)
    labels = tuple(scene.node_semantic_labels)
    authored = [False] * len(taxonomies)
    resolved: list[tuple[str, str] | None] = [None] * len(taxonomies)
    visiting: set[int] = set()

    def resolve(node: int) -> tuple[str, str]:
        cached = resolved[node]
        if cached is not None:
            return cached
        if node in visiting:
            raise ValueError("USD: node hierarchy contains a cycle")
        visiting.add(node)
        taxonomy, label = taxonomies[node], labels[node]
        if taxonomy and not _IDENTIFIER.fullmatch(taxonomy):
            raise ValueError(
                f"USD: semantic taxonomy {taxonomy!r} is not a portable "
                "identifier"
            )
        parent = int(parents[node])
        parent_pair = ("", "") if parent < 0 else resolve(parent)
        pair = (taxonomy, label)
        if parent_pair != ("", "") and pair != parent_pair:
            raise ValueError(
                "USD: evaluated semantic labels cannot clear or replace an "
                "inherited taxonomy/label pair"
            )
        authored[node] = pair != ("", "") and parent_pair == ("", "")
        resolved[node] = pair
        visiting.remove(node)
        return pair

    for node in range(len(taxonomies)):
        resolve(node)
    return tuple(authored)


def api_schema(scene, node: int, authored: tuple[bool, ...]) -> str | None:
    """Return the multiple-apply schema name for one authoring point."""

    if not authored[node]:
        return None
    return _API_PREFIX + scene.node_semantic_taxonomies[node]


def write_label_attribute(scene, node: int, stream, *, inner: str) -> None:
    """Write one direct label at a validated semantic authoring point."""

    taxonomy = scene.node_semantic_taxonomies[node]
    label = scene.node_semantic_labels[node]
    stream.write(
        f"{inner}token[] {_PROPERTY_PREFIX}{taxonomy} = "
        f"[{json.dumps(label, ensure_ascii=False)}]\n"
    )


__all__ = [
    "api_schema",
    "inherited_pair",
    "semantic_properties",
    "validate_writable_semantics",
    "write_label_attribute",
]
