"""AST-level import guards over the sceneapi_io package.

1. ``sceneapi_io`` imports nothing from the SceneAPI family
   (``sceneapi`` / ``sfm_hub`` / ``sfmapi`` / ``app``) — the leaf
   property the contract plane depends on.
2. ``sceneapi_io.mapping`` and ``sceneapi_io.matching`` never import
   each other (the extraction option for each domain contract). Both
   may import ``sceneapi_io.data``.
3. Every name in each namespace's ``__all__`` imports.
4. ``import sceneapi_io.testing`` never imports pytest (pytest stays a
   lazy, in-function import) — verified in a subprocess.
"""

from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

import sceneapi_io

SRC_ROOT = Path(sceneapi_io.__file__).resolve().parent

FORBIDDEN_FAMILY_ROOTS = {"sceneapi", "sfm_hub", "sfmapi", "app"}


def _package_files() -> list[Path]:
    files = sorted(SRC_ROOT.rglob("*.py"))
    assert files, f"no python files found under {SRC_ROOT}"
    return files


def _imported_modules(path: Path) -> set[str]:
    """All absolute module names imported by ``path``.

    Relative imports are resolved against the file's package so a
    ``from ..matching import x`` cannot slip past the guard.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package_parts = ("sceneapi_io", *path.relative_to(SRC_ROOT).parent.parts)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                assert node.module is not None
                modules.add(node.module)
            else:
                base = package_parts[: len(package_parts) - (node.level - 1)]
                prefix = ".".join(base)
                modules.add(f"{prefix}.{node.module}" if node.module else prefix)
    return modules


@pytest.mark.parametrize("path", _package_files(), ids=lambda p: str(p.relative_to(SRC_ROOT)))
def test_no_family_imports(path: Path) -> None:
    for module in _imported_modules(path):
        root = module.split(".", 1)[0]
        assert root not in FORBIDDEN_FAMILY_ROOTS, (
            f"{path.relative_to(SRC_ROOT)} imports {module!r} — sceneapi_io is a "
            f"leaf and must import nothing from the SceneAPI family"
        )


@pytest.mark.parametrize(
    ("namespace", "forbidden_sibling"),
    [("mapping", "matching"), ("matching", "mapping")],
)
def test_mapping_and_matching_never_import_each_other(
    namespace: str, forbidden_sibling: str
) -> None:
    namespace_dir = SRC_ROOT / namespace
    files = sorted(namespace_dir.rglob("*.py"))
    assert files, f"no python files under {namespace_dir}"
    forbidden_prefix = f"sceneapi_io.{forbidden_sibling}"
    for path in files:
        for module in _imported_modules(path):
            imports_sibling = module == forbidden_prefix or module.startswith(
                forbidden_prefix + "."
            )
            assert not imports_sibling, (
                f"{path.relative_to(SRC_ROOT)} imports {module!r} — mapping/ and "
                f"matching/ must stay import-isolated from each other"
            )


def test_mapping_and_matching_may_import_data() -> None:
    # Positive control: the isolation guard must not be trivially green.
    mapping_imports = _imported_modules(SRC_ROOT / "mapping" / "__init__.py")
    matching_imports = _imported_modules(SRC_ROOT / "matching" / "__init__.py")
    assert any(m.startswith("sceneapi_io.data") for m in mapping_imports)
    assert any(m.startswith("sceneapi_io.data") for m in matching_imports)


@pytest.mark.parametrize(
    "namespace",
    [
        "sceneapi_io",
        "sceneapi_io.data",
        "sceneapi_io.formats",
        "sceneapi_io.mapping",
        "sceneapi_io.matching",
        "sceneapi_io.testing",
    ],
)
def test_public_surface_imports(namespace: str) -> None:
    module = importlib.import_module(namespace)
    exported = getattr(module, "__all__", None)
    assert exported, f"{namespace} must declare a non-empty __all__"
    for name in exported:
        assert hasattr(module, name), f"{namespace}.{name} listed in __all__ but missing"
        assert getattr(module, name) is not None


def test_testing_module_import_is_pytest_free() -> None:
    code = (
        "import sys\n"
        "import sceneapi_io.testing\n"
        "assert 'pytest' not in sys.modules, "
        "'importing sceneapi_io.testing must not import pytest'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_plain_import_is_numpy_lazy() -> None:
    # `import sceneapi_io` alone must not pull numpy — the numpy-native
    # contracts live in the lazily-imported namespaces.
    code = (
        "import sys\n"
        "import sceneapi_io\n"
        "assert 'numpy' not in sys.modules, "
        "'plain `import sceneapi_io` should not import numpy'\n"
        "import sceneapi_io.data\n"
        "assert 'numpy' in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
