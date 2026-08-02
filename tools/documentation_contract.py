"""Synchronize generated documentation facts with SceneIO's live registry.

The contract deliberately covers current, mechanically knowable claims. It
does not rewrite historical checkpoints or prose that requires human review.
"""

from __future__ import annotations

import argparse
import textwrap
import tomllib
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import sceneio
from sceneio.io._builtin_manifest import CANONICAL_BUILTIN_IDS
from sceneio.io.registry import CodecCapabilities, NativeFeatureCapabilities

ROOT = Path(__file__).parents[1]
CONTRACT_PATH = Path("tests/contracts/documentation_v1.toml")
REPOSITORY_COVERAGE_PATH = Path("tests/contracts/repository_coverage_v1.toml")


class DocumentationContractError(ValueError):
    """A documentation contract or generated section is inconsistent."""


@dataclass(frozen=True, slots=True)
class GeneratedSection:
    """One marker-delimited generated section declared by the contract."""

    document: PurePosixPath
    marker: str
    renderer: str


@dataclass(frozen=True, slots=True)
class DocumentationContract:
    """Parsed and validated documentation contract."""

    expected_builtin_count: int
    canonical_current_document: PurePosixPath
    readme_entry_points: tuple[PurePosixPath, ...]
    generated_sections: tuple[GeneratedSection, ...]


def _load_toml(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def load_contract(root: Path = ROOT) -> DocumentationContract:
    """Load and validate the repository's documentation contract."""

    raw = _load_toml(root / CONTRACT_PATH)
    if raw.get("schema_version") != 1:
        raise DocumentationContractError("documentation schema_version must be 1")
    expected_sources = {
        "inventory_source": (
            "sceneio.io._builtin_manifest.CANONICAL_BUILTIN_IDS"
        ),
        "capability_source": "sceneio.capabilities",
        "native_feature_source": "sceneio.native_features",
    }
    for field, expected in expected_sources.items():
        if raw.get(field) != expected:
            raise DocumentationContractError(
                f"{field} must name the authoritative source {expected!r}"
            )

    expected_count = raw.get("expected_builtin_count")
    if expected_count != len(CANONICAL_BUILTIN_IDS):
        raise DocumentationContractError(
            "expected_builtin_count disagrees with CANONICAL_BUILTIN_IDS: "
            f"{expected_count!r} != {len(CANONICAL_BUILTIN_IDS)}"
        )

    canonical = _repository_path(
        root, raw.get("canonical_current_document"), "canonical_current_document"
    )
    entry_points = tuple(
        _repository_path(root, item, "readme_entry_points")
        for item in raw.get("readme_entry_points", ())
    )
    if not entry_points:
        raise DocumentationContractError("readme_entry_points must not be empty")

    sections = tuple(
        GeneratedSection(
            document=_repository_path(
                root, item.get("document"), "generated_section.document"
            ),
            marker=_required_text(item, "marker"),
            renderer=_required_text(item, "renderer"),
        )
        for item in raw.get("generated_section", ())
    )
    if not sections:
        raise DocumentationContractError("generated_section must not be empty")
    identities = [(section.document, section.marker) for section in sections]
    if len(set(identities)) != len(identities):
        raise DocumentationContractError("generated sections must be unique")
    unknown_renderers = sorted(
        {section.renderer for section in sections} - set(_RENDERERS)
    )
    if unknown_renderers:
        raise DocumentationContractError(
            f"unknown documentation renderers: {', '.join(unknown_renderers)}"
        )

    repository_coverage = _load_toml(root / REPOSITORY_COVERAGE_PATH)
    declared_count = repository_coverage.get("builtins")
    codec_count = len(repository_coverage.get("codec", ()))
    if declared_count != expected_count or codec_count != expected_count:
        raise DocumentationContractError(
            "repository coverage counts disagree with the documentation contract: "
            f"declared={declared_count!r}, entries={codec_count}, "
            f"expected={expected_count}"
        )

    return DocumentationContract(
        expected_builtin_count=expected_count,
        canonical_current_document=canonical,
        readme_entry_points=entry_points,
        generated_sections=sections,
    )


def _required_text(item: Mapping[str, Any], field: str) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value:
        raise DocumentationContractError(f"{field} must be a non-empty string")
    return value


def _repository_path(root: Path, value: Any, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise DocumentationContractError(f"{field} must be a non-empty path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise DocumentationContractError(
            f"{field} must be a repository-relative POSIX path"
        )
    resolved = root.joinpath(*path.parts)
    if not resolved.is_file():
        raise DocumentationContractError(f"{field} does not exist: {value}")
    return path


def _capabilities() -> Mapping[str, CodecCapabilities]:
    capabilities = sceneio.capabilities()
    if set(capabilities) != set(CANONICAL_BUILTIN_IDS):
        missing = sorted(set(CANONICAL_BUILTIN_IDS) - set(capabilities))
        unexpected = sorted(set(capabilities) - set(CANONICAL_BUILTIN_IDS))
        raise DocumentationContractError(
            f"capability inventory mismatch: missing={missing}, unexpected={unexpected}"
        )
    return capabilities


def render_inventory_summary(
    capabilities: Mapping[str, CodecCapabilities],
    _native_features: Mapping[str, NativeFeatureCapabilities],
) -> str:
    """Render current aggregate registry facts."""

    containers = Counter(cap.container_kind for cap in capabilities.values())
    unknown_containers = set(containers) - {"file", "directory", "multi_file"}
    if unknown_containers:
        raise DocumentationContractError(
            f"unknown container kinds: {sorted(unknown_containers)}"
        )
    total = len(capabilities)
    readable = sum(cap.can_read for cap in capabilities.values())
    writable = sum(cap.can_write for cap in capabilities.values())
    inspectable = sum(cap.can_inspect for cap in capabilities.values())
    partial_codecs = sum(bool(cap.partial_selectors) for cap in capabilities.values())
    selectors = sum(len(cap.partial_selectors) for cap in capabilities.values())
    stream_reads = sum(cap.streams_read for cap in capabilities.values())
    stream_writes = sum(cap.streams_write for cap in capabilities.values())
    summary = (
        "**Generated registry contract:** SceneIO has "
        f"**{total} built-in formats**: **{containers['file']}** single-file, "
        f"**{containers['directory']}** directory, and "
        f"**{containers['multi_file']}** multi-file containers. "
        f"**{readable}** are readable, **{writable}** writable, and "
        f"**{inspectable}** inspectable; **{partial_codecs}** formats expose "
        f"**{selectors}** bounded partial selectors. **{stream_reads}** provide "
        f"streaming reads and **{stream_writes}** provide streaming writes. "
        "The values come directly from `CANONICAL_BUILTIN_IDS` and "
        "`sceneio.capabilities()`."
    )
    return "\n".join(
        textwrap.wrap(
            summary,
            width=88,
            break_long_words=False,
            break_on_hyphens=False,
        )
    )


def render_capability_rows(
    capabilities: Mapping[str, CodecCapabilities],
    _native_features: Mapping[str, NativeFeatureCapabilities],
) -> str:
    """Render the per-format public capability table rows."""

    rows = []
    for format_id, cap in sorted(capabilities.items()):
        partial = ", ".join(cap.partial_selectors) or "-"
        requires = ", ".join(cap.requires_features) or "-"
        rows.append(
            f"| `{format_id}` | {cap.container_kind} | "
            f"{'yes' if cap.can_read else 'no'} | "
            f"{'yes' if cap.can_write else 'no'} | "
            f"{'yes' if cap.can_inspect else 'no'} | {partial} | "
            f"{'yes' if cap.streams_read else 'no'} | "
            f"{'yes' if cap.streams_write else 'no'} | "
            f"{'yes' if cap.lossy else 'no'} | {requires} |"
        )
    return "\n".join(rows)


def render_native_feature_rows(
    _capabilities: Mapping[str, CodecCapabilities],
    native_features: Mapping[str, NativeFeatureCapabilities],
) -> str:
    """Render the optional native-feature table rows."""

    rows = []
    for name, feature in native_features.items():
        formats = ", ".join(f"`{item}`" for item in feature.formats)
        rows.append(
            f"| `{name}` | `{feature.build_option}` | "
            f"{'yes' if feature.available else 'no'} | {formats} |"
        )
    return "\n".join(rows)


def render_partial_selector_rows(
    capabilities: Mapping[str, CodecCapabilities],
    _native_features: Mapping[str, NativeFeatureCapabilities],
) -> str:
    """Render the selector-to-codec summary."""

    selectors: dict[str, list[str]] = {}
    for format_id in CANONICAL_BUILTIN_IDS:
        for selector in capabilities[format_id].partial_selectors:
            selectors.setdefault(selector, []).append(format_id)
    rows = ["| Selector | Built-in codecs |", "|---|---|"]
    for selector, format_ids in sorted(selectors.items()):
        formats = ", ".join(f"`{format_id}`" for format_id in sorted(format_ids))
        rows.append(f"| `{selector}` | {formats} |")
    return "\n".join(rows)


Renderer = Callable[
    [Mapping[str, CodecCapabilities], Mapping[str, NativeFeatureCapabilities]], str
]
_RENDERERS: Mapping[str, Renderer] = {
    "inventory_summary": render_inventory_summary,
    "capability_rows": render_capability_rows,
    "native_feature_rows": render_native_feature_rows,
    "partial_selector_rows": render_partial_selector_rows,
}


def replace_generated_section(document: str, marker: str, content: str) -> str:
    """Replace exactly one marker-delimited section."""

    start = f"<!-- {marker}:start -->"
    end = f"<!-- {marker}:end -->"
    if document.count(start) != 1 or document.count(end) != 1:
        raise DocumentationContractError(
            f"expected exactly one {start!r} and one {end!r} marker"
        )
    prefix, remainder = document.split(start, maxsplit=1)
    _old, suffix = remainder.split(end, maxsplit=1)
    return f"{prefix}{start}\n{content.rstrip()}\n{end}{suffix}"


def synchronize_documentation(
    *, root: Path = ROOT, write: bool = False
) -> tuple[PurePosixPath, ...]:
    """Return drifted documents, optionally rewriting their generated sections."""

    contract = load_contract(root)
    capabilities = _capabilities()
    native_features = sceneio.native_features()
    documents: dict[PurePosixPath, str] = {}
    originals: dict[PurePosixPath, str] = {}
    for section in contract.generated_sections:
        if section.document not in documents:
            path = root.joinpath(*section.document.parts)
            documents[section.document] = path.read_text(encoding="utf-8")
            originals[section.document] = documents[section.document]
        rendered = _RENDERERS[section.renderer](capabilities, native_features)
        documents[section.document] = replace_generated_section(
            documents[section.document], section.marker, rendered
        )

    drifted = tuple(
        document
        for document, current in documents.items()
        if current != originals[document]
    )
    if write:
        for document in drifted:
            root.joinpath(*document.parts).write_text(
                documents[document], encoding="utf-8", newline="\n"
            )
    return drifted


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="fail when a generated section differs (the default)",
    )
    mode.add_argument(
        "--write", action="store_true", help="rewrite drifted generated sections"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        drifted = synchronize_documentation(write=args.write)
    except DocumentationContractError as exc:
        print(f"documentation contract error: {exc}")
        return 2
    if args.write:
        for document in drifted:
            print(f"updated {document.as_posix()}")
        return 0
    if drifted:
        print("generated documentation is stale; run:")
        print("  .venv/Scripts/python.exe tools/documentation_contract.py --write")
        for document in drifted:
            print(f"  - {document.as_posix()}")
        return 1
    print("documentation contract is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
