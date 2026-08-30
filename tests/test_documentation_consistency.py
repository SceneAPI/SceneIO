"""Consistency checks for the active documentation and completed-plan archive."""

from __future__ import annotations

import ast
import hashlib
import html
import importlib
import re
import tomllib
import unicodedata
from collections import Counter
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

import pytest

import sceneio
from sceneio.io._builtin_manifest import CANONICAL_BUILTIN_IDS
from sceneio.representations import REPRESENTATION_CONTRACTS
from tools import documentation_contract

ROOT = Path(__file__).parents[1]
DOCS = ROOT / "docs"
ACTIVE_PLAN = DOCS / "format_gap_implementation_plan.md"
ARCHIVE_DIR = DOCS / "plans" / "completed"
ARCHIVE = ARCHIVE_DIR / "format_gap_waves_a_c_2026-07-25.md"
ARCHIVE_PAYLOAD_DIGESTS = {
    "format_gap_waves_a_c_2026-07-25.md": (
        "### 12.2 Wave A — typed-depth slice complete locally",
        "\n---\n",
        "91e5f41f9147ee80a213cc8c7d4c399db13fd83bdc4710fd2b4adde2ae2c28ca",
    ),
    "remaining_gap_implementation_plan_2026-08-29.md": (
        "# Remaining-gap implementation plan",
        "<!-- immutable-archive:end -->",
        "f5deaa7c4b8fbae09514fa9b79ccfc09b229030bcb13fb524983d1ee3ecb3acf",
    ),
    "public_type_contract_standardization_2026-08-29.md": (
        "# Public type-contract standardization implementation plan",
        "<!-- immutable-archive:end -->",
        "61afd05dfd6c30ace5f507277f36027c4b067257e594d3f687b553c56d00145c",
    ),
}
_INLINE_LINK = re.compile(
    r"!?\[[^\]]*\]\((?P<target><[^>]+>|[^\s)]+)"
)
_REFERENCE_LINK = re.compile(r"^\[[^\]]+\]:\s*(?P<target>\S+)", re.MULTILINE)
_HEADING = re.compile(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_EXPLICIT_ID = re.compile(r"<(?:a|[A-Za-z][^>]*)\s+[^>]*id=[\"']([^\"']+)")
_FENCE = re.compile(r"^(?:```|~~~)")


def _documents() -> tuple[Path, ...]:
    return (ROOT / "README.md", *sorted(DOCS.rglob("*.md")))


def _without_fenced_code(document: str) -> str:
    kept: list[str] = []
    fence: str | None = None
    for line in document.splitlines(keepends=True):
        stripped = line.lstrip()
        match = _FENCE.match(stripped)
        if match:
            marker = match.group(0)
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is None:
            kept.append(line)
    return "".join(kept)


def _destinations(document: str) -> set[str]:
    visible = _without_fenced_code(document)
    targets = {
        match.group("target").strip("<>")
        for match in _INLINE_LINK.finditer(visible)
    }
    targets.update(
        match.group("target").strip("<>")
        for match in _REFERENCE_LINK.finditer(visible)
    )
    return targets


def _github_slug(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("`", "").lower().strip()
    return "".join(
        character
        for character in value
        if (
            character in "-_"
            or character.isspace()
            or not unicodedata.category(character).startswith(("P", "S"))
        )
    ).replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    document = path.read_text(encoding="utf-8")
    anchors = set(_EXPLICIT_ID.findall(document))
    occurrences: dict[str, int] = {}
    for heading in _HEADING.findall(_without_fenced_code(document)):
        base = _github_slug(heading)
        count = occurrences.get(base, 0)
        occurrences[base] = count + 1
        anchors.add(base if count == 0 else f"{base}-{count}")
    return anchors


def _resolve_relative_with_exact_case(source: Path, path_text: str) -> Path:
    assert "\\" not in path_text, "Markdown links must use forward slashes"
    if not path_text:
        return source.resolve()

    relative = PurePosixPath(path_text)
    assert not relative.is_absolute(), "local Markdown link must be relative"
    current = source.parent
    for component in relative.parts:
        if component == ".":
            continue
        if component == "..":
            current = current.parent
            try:
                current.relative_to(ROOT)
            except ValueError as exc:
                raise AssertionError("relative link leaves the repository") from exc
            continue
        assert current.is_dir(), f"link parent is not a directory: {current}"
        names = {entry.name for entry in current.iterdir()}
        assert component in names, (
            f"relative link is missing or has incorrect case: {path_text}"
        )
        current /= component
    resolved = current.resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError as exc:
        raise AssertionError("relative link leaves the repository") from exc
    return resolved


def test_relative_markdown_links_resolve_with_exact_case_and_valid_anchors():
    failures: list[str] = []
    for source in _documents():
        document = source.read_text(encoding="utf-8")
        for raw_target in sorted(_destinations(document)):
            target = unquote(raw_target)
            if target.startswith(("http://", "https://", "mailto:", "data:")):
                continue
            path_text, _, fragment = target.partition("#")
            try:
                resolved = _resolve_relative_with_exact_case(source, path_text)
            except AssertionError as exc:
                failures.append(f"{source.relative_to(ROOT)} -> {target}: {exc}")
                continue
            if not resolved.exists():
                failures.append(
                    f"{source.relative_to(ROOT)} -> {target}: missing target"
                )
                continue
            if (
                fragment
                and resolved.is_file()
                and resolved.suffix == ".md"
                and fragment not in _anchors(resolved)
            ):
                failures.append(
                    f"{source.relative_to(ROOT)} -> {target}: missing anchor"
                )
    assert not failures, "\n".join(failures)


def test_markdown_fences_are_balanced():
    failures: list[str] = []
    for source in _documents():
        fence: str | None = None
        start_line: int | None = None
        for line_number, line in enumerate(
            source.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = _FENCE.match(line.lstrip())
            if not match:
                continue
            marker = match.group(0)
            if fence is None:
                fence = marker
                start_line = line_number
            elif marker == fence:
                fence = None
                start_line = None
        if fence is not None:
            failures.append(
                f"{source.relative_to(ROOT)}:{start_line}: unclosed {fence} fence"
            )
    assert not failures, "\n".join(failures)


def test_exact_case_check_uses_lexical_link_components_on_windows():
    with pytest.raises(AssertionError, match="incorrect case"):
        _resolve_relative_with_exact_case(
            ROOT / "README.md", "DOCS/format_coverage.md"
        )


def test_readme_links_every_authoritative_engineering_entry_point():
    targets = _destinations((ROOT / "README.md").read_text(encoding="utf-8"))
    contract = documentation_contract.load_contract(ROOT)
    assert {
        path.as_posix() for path in contract.readme_entry_points
    } <= targets


def test_representation_count_claims_match_runtime_catalog():
    count = len(REPRESENTATION_CONTRACTS)
    claims = {
        ROOT / "CHANGELOG.md": f"all {count} public data representations",
        ROOT / "README.md": f"exact {count}-record catalog",
        DOCS / "coverage_roadmap.md": (
            f"covers all {count} public representation classes"
        ),
        DOCS / "format_coverage.md": (
            f"classifies all {count} public data representations"
        ),
        DOCS / "releases" / "v0.3.0.md": (
            f"All {count} public in-memory data representations"
        ),
        DOCS / "representation_normalization.md": (
            f"Version 1 covers {count} representations"
        ),
    }
    for path, claim in claims.items():
        assert claim in path.read_text(encoding="utf-8"), path.relative_to(ROOT)


def test_generated_current_facts_match_authoritative_runtime_sources():
    assert documentation_contract.synchronize_documentation(root=ROOT) == ()
    summaries = []
    for path in (ROOT / "README.md", DOCS / "format_coverage.md"):
        document = path.read_text(encoding="utf-8")
        match = re.search(
            r"<!-- sceneio-inventory-summary:start -->\n"
            r"(.*?)\n"
            r"<!-- sceneio-inventory-summary:end -->",
            document,
            re.DOTALL,
        )
        assert match is not None
        summaries.append(" ".join(match.group(1).split()))
    assert len(set(summaries)) == 1

    capabilities = sceneio.capabilities()
    containers = Counter(cap.container_kind for cap in capabilities.values())
    expected = (
        "**Generated registry contract:** SceneIO has "
        f"**{len(capabilities)} built-in formats**: **{containers['file']}** "
        f"single-file, **{containers['directory']}** directory, and "
        f"**{containers['multi_file']}** multi-file containers. "
        f"**{sum(cap.can_read for cap in capabilities.values())}** are readable, "
        f"**{sum(cap.can_write for cap in capabilities.values())}** writable, and "
        f"**{sum(cap.can_inspect for cap in capabilities.values())}** inspectable; "
        f"**{sum(bool(cap.partial_selectors) for cap in capabilities.values())}** "
        "formats expose "
        f"**{sum(len(cap.partial_selectors) for cap in capabilities.values())}** "
        "bounded partial selectors. "
        f"**{sum(cap.streams_read for cap in capabilities.values())}** provide "
        "streaming reads and "
        f"**{sum(cap.streams_write for cap in capabilities.values())}** provide "
        "streaming writes. The values come directly from "
        "`CANONICAL_BUILTIN_IDS` and `sceneio.capabilities()`."
    )
    assert summaries == [expected, expected]


def test_generated_architecture_facts_match_ownership_manifest():
    expected = documentation_contract.render_architecture_summary(
        sceneio.capabilities(), sceneio.native_features()
    )
    for path in (
        DOCS / "core_architecture.md",
        DOCS / "repository_organization_plan.md",
    ):
        document = path.read_text(encoding="utf-8")
        match = re.search(
            r"<!-- sceneio-architecture-summary:start -->\n"
            r"(.*?)\n"
            r"<!-- sceneio-architecture-summary:end -->",
            document,
            re.DOTALL,
        )
        assert match is not None
        assert match.group(1) == expected


def test_release_version_surfaces_agree():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    assert sceneio.__version__ == version

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"- Version: `{version}`" in readme

    native_sog = (ROOT / "src/cpp/codecs/splats/sog.cpp").read_text(
        encoding="utf-8"
    )
    assert f'"SceneIO {version}"' in native_sog

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{version}]" in changelog
    assert (DOCS / "releases" / f"v{version}.md").is_file()

    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked_sceneio = [
        package for package in lock["package"] if package["name"] == "sceneio"
    ]
    assert len(locked_sceneio) == 1
    assert locked_sceneio[0]["version"] == version


def test_builtin_count_contract_rejects_stale_metadata(monkeypatch):
    monkeypatch.setattr(
        documentation_contract,
        "CANONICAL_BUILTIN_IDS",
        CANONICAL_BUILTIN_IDS[:-1],
    )
    with pytest.raises(
        documentation_contract.DocumentationContractError,
        match="expected_builtin_count disagrees",
    ):
        documentation_contract.load_contract(ROOT)


def test_generated_section_requires_one_balanced_marker_pair():
    assert documentation_contract.replace_generated_section(
        "<!-- example:start -->\nstale\n<!-- example:end -->",
        "example",
        "current",
    ) == "<!-- example:start -->\ncurrent\n<!-- example:end -->"
    with pytest.raises(
        documentation_contract.DocumentationContractError,
        match="expected exactly one",
    ):
        documentation_contract.replace_generated_section(
            "<!-- example:start -->\nold", "example", "new"
        )


def test_document_roles_and_checkpoint_ownership_are_explicit():
    coverage = (DOCS / "format_coverage.md").read_text(encoding="utf-8")
    roadmap = (DOCS / "coverage_roadmap.md").read_text(encoding="utf-8")
    active = ACTIVE_PLAN.read_text(encoding="utf-8")

    assert "canonical source" in coverage
    assert "current codec capabilities and\nvalidation status" in coverage
    assert "intentionally does not duplicate" in roadmap
    assert "github.com/SceneAPI/SceneIO/actions/runs/" not in roadmap
    assert "**historical dependency queue**" in active
    assert "**active dependency queue**" not in active
    assert "The format-expansion program shipped in SceneIO 0.3.0" in active
    assert "[`plans/completed/`](plans/completed/README.md)" in active
    preamble = active.split("## 1. Outcome and boundaries", maxsplit=1)[0]
    assert "`a5e7fa4`" not in preamble
    assert "50 compiled codecs" not in preamble
    assert "[`format_coverage.md`](format_coverage.md)" in preamble

    checkpoint = active.split("Status terms are strict:", maxsplit=1)[0]
    checkpoint = checkpoint.rsplit(
        "### 12.1 Current checkpoint and status vocabulary", maxsplit=1
    )[1]
    assert "github.com/SceneAPI/SceneIO/actions/runs/" not in checkpoint


def test_readme_installation_metadata_matches_pyproject():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert f"- Python: `{project['requires-python']}`" in readme
    for dependency in project["dependencies"]:
        assert f"`{dependency}`" in readme

    match = re.search(r'python -m pip install "sceneio\[([^]]+)\]"', readme)
    assert match is not None
    documented_extras = set(match.group(1).split(","))
    runtime_extras = set(project["optional-dependencies"]) - {"dev", "test"}
    assert documented_extras == runtime_extras
    assert "uv run python -m pytest -q" in readme
    assert "uv run pytest -q" not in readme


def test_readme_python_examples_parse_and_reference_public_symbols():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```python\n(.*?)\n```", readme, re.DOTALL)
    assert blocks

    for index, block in enumerate(blocks, start=1):
        tree = ast.parse(block, filename=f"README.md python block {index}")
        uses_sceneio_name = any(
            isinstance(node, ast.Name)
            and node.id == "sceneio"
            and isinstance(node.ctx, ast.Load)
            for node in ast.walk(tree)
        )
        imports_sceneio_name = any(
            isinstance(node, ast.Import)
            and any(alias.name == "sceneio" for alias in node.names)
            for node in tree.body
        )
        assert not uses_sceneio_name or imports_sceneio_name, (
            f"README block {index} uses sceneio without importing it"
        )
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "sceneio"
            ):
                assert hasattr(sceneio, node.attr), (
                    f"README block {index} references missing sceneio.{node.attr}"
                )
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and (
                    node.module == "sceneio"
                    or node.module.startswith("sceneio.")
                )
            ):
                module = importlib.import_module(node.module)
                for alias in node.names:
                    if alias.name != "*":
                        assert hasattr(module, alias.name), (
                            f"README block {index} imports missing "
                            f"{node.module}.{alias.name}"
                        )

    assert 'assert not sceneio.native_features("hdf5").available' not in readme

    gaussian = sceneio.representation_contract(sceneio.GaussianCloud)
    assert gaussian.profile.id == "gaussian_cloud"
    assert gaussian.coordinates == "record_declared"
    assert 'assert contract.coordinates == "record_declared"' in readme


def test_all_python_documentation_fences_parse():
    for source in _documents():
        document = source.read_text(encoding="utf-8")
        for index, block in enumerate(
            re.findall(r"```python\n(.*?)\n```", document, re.DOTALL),
            start=1,
        ):
            ast.parse(
                block,
                filename=f"{source.relative_to(ROOT)} python block {index}",
            )


def test_current_document_preambles_do_not_reassert_superseded_counts_or_state():
    index = (DOCS / "README.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    survey = (DOCS / "formats_survey.md").read_text(encoding="utf-8")
    large_io = (DOCS / "large_file_io_benchmark_spec.md").read_text(
        encoding="utf-8"
    )
    adapters = (DOCS / "colmap_adapters.md").read_text(encoding="utf-8")
    closure = (DOCS / "remaining_3dcv_profile_checklist.md").read_text(
        encoding="utf-8"
    )
    coverage = (DOCS / "format_coverage.md").read_text(encoding="utf-8")

    assert "[`documentation index`](docs/README.md)" in readme
    assert "Current user and API contracts" in index
    assert "Completed implementation records" in index
    assert "supports 72 bounded format ids" not in survey
    assert "complete 73-format regression" not in large_io
    assert "entry in the 54-codec registry" not in adapters
    assert "The validated closure shipped in" in closure
    assert "Pending — declared roadmap gaps" not in coverage
    assert "In progress — Phase 7" not in coverage


def test_release_notes_record_published_tag_and_immutable_description_correction():
    release = (DOCS / "releases" / "v0.3.0.md").read_text(encoding="utf-8")
    assert "releases/tag/v0.3.0" in release
    assert "actions/runs/33269098190" in release
    assert "immutable PyPI 0.3.0 long description" in release
    assert "runtime and current repository contract contain 103" in release


def test_completed_archive_is_indexed_reachable_and_immutable():
    index = (ARCHIVE_DIR / "README.md").read_text(encoding="utf-8")
    indexed = {
        target.partition("#")[0]
        for target in _destinations(index)
        if target.endswith(".md") and "/" not in target
    }
    archive_names = {
        path.name for path in ARCHIVE_DIR.glob("*.md") if path.name != "README.md"
    }
    assert indexed == archive_names
    assert set(ARCHIVE_PAYLOAD_DIGESTS) == archive_names

    active = ACTIVE_PLAN.read_text(encoding="utf-8")
    archived = ARCHIVE.read_text(encoding="utf-8")
    for heading in (
        "### 12.2 Wave A — typed-depth slice complete locally",
        "### 12.3 Wave B — finish default-wheel, self-contained G2 coverage",
        "### 12.4 Wave C — canonical mesh tier",
    ):
        assert active.count(heading) == 1
        assert archived.count(heading) == 1
    assert "#### A1." not in active
    assert "#### B1." not in active
    assert "#### C1." not in active
    assert "plans/completed/format_gap_waves_a_c_2026-07-25.md" in active
    assert "../../format_gap_implementation_plan.md" in archived
    assert "docs/plans/completed/README.md" in (
        ROOT / "README.md"
    ).read_text(encoding="utf-8")
    remaining_stub = (DOCS / "remaining_gap_implementation_plan.md").read_text(
        encoding="utf-8"
    )
    assert "plans/completed/remaining_gap_implementation_plan_2026-08-29.md" in (
        remaining_stub
    )
    closure = (DOCS / "remaining_3dcv_profile_checklist.md").read_text(
        encoding="utf-8"
    )
    assert "Complete and merged as of 2026-08-29" in closure
    assert "content-hash contract deliberately" in closure
    archive_targets = _destinations(archived)
    assert {
        "../../format_gap_implementation_plan.md#129-per-commit-verification-gate",
        "../../format_coverage.md#format--data-structure-coverage",
        "../../format_gap_implementation_plan.md#1210-dependency-wave-validation-gate",
    } <= archive_targets

    for filename, (start_marker, end_marker, expected) in (
        ARCHIVE_PAYLOAD_DIGESTS.items()
    ):
        document = (ARCHIVE_DIR / filename).read_text(encoding="utf-8")
        start = document.index(start_marker)
        stop = document.rindex(end_marker)
        digest = hashlib.sha256(document[start:stop].encode()).hexdigest()
        assert digest == expected


def _partial_summary_rows() -> str:
    selectors: dict[str, list[str]] = {}
    for format_id in CANONICAL_BUILTIN_IDS:
        capability = sceneio.capabilities(format_id)
        for selector in capability.partial_selectors:
            selectors.setdefault(selector, []).append(format_id)
    rows = ["| Selector | Built-in codecs |", "|---|---|"]
    for selector, format_ids in sorted(selectors.items()):
        formats = ", ".join(f"`{format_id}`" for format_id in sorted(format_ids))
        rows.append(f"| `{selector}` | {formats} |")
    return "\n".join(rows)


def test_human_partial_selector_summary_matches_generated_capabilities():
    architecture = (DOCS / "core_architecture.md").read_text(encoding="utf-8")
    match = re.search(
        r"<!-- sceneio-partial-summary:start -->\n"
        r"(.*?)\n"
        r"<!-- sceneio-partial-summary:end -->",
        architecture,
        re.DOTALL,
    )
    assert match is not None
    assert match.group(1) == _partial_summary_rows()
    assert "| `mesh_id` | `glb`, `gltf` |" in match.group(1)
    assert "| `primitive_id` | `glb`, `gltf` |" in match.group(1)
