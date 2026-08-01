"""Tests for the sdist/wheel inventory checker used by the release workflow."""

from __future__ import annotations

import importlib.util
import io
import re
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "tools" / "verify_distribution.py"
SPEC = importlib.util.spec_from_file_location("verify_distribution", VERIFIER_PATH)
assert SPEC is not None and SPEC.loader is not None
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
WINDOWS_CORE = "sceneio/_core.pyd"
# Exact bootstrap emitted by MIT-licensed delvewheel 1.13.0 for this wheel;
# see LICENSES/delvewheel.txt.
DELVEWHEEL_PATCH = b"""# start delvewheel patch
def _delvewheel_patch_1_13_0():
    import os
    if os.path.isdir(libs_dir := os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, 'sceneio.libs'))):
        os.add_dll_directory(libs_dir)


_delvewheel_patch_1_13_0()
del _delvewheel_patch_1_13_0
# end delvewheel patch
"""
DELVEWHEEL_METADATA = (
    b"Version: 1.13.0\n"
    b"Arguments: ['delvewheel/__main__.py', 'repair', '--add-path', "
    b"'Microsoft.VC143.CRT', '-w', 'wheelhouse', 'sceneio.whl']\n\n"
)


def _delvewheel_fixture(newline: bytes = b"\n") -> tuple[bytes, bytes]:
    original = (
        b'"""sceneio package."""'
        + newline * 2
        + b"from __future__ import annotations"
        + newline * 2
        + b"VALUE = 1"
        + newline
    )
    patched = (
        b'"""sceneio package."""'
        + newline * 2
        + b"from __future__ import annotations"
        + newline * 3
        + DELVEWHEEL_PATCH.replace(b"\n", newline)
        + newline
        + b"VALUE = 1"
        + newline
    )
    return original, patched


def _complete_delvewheel_payload(
    package_payload: bytes,
    *,
    runtime: str = "sceneio.libs/msvcp140.dll",
    metadata: bytes = DELVEWHEEL_METADATA,
) -> dict[str, object]:
    return {
        "package_payload": package_payload,
        "extra_member": runtime,
        "extra_payload": b"MZruntime",
        "delvewheel_metadata": metadata,
    }


def _source_root(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    licenses = source / "LICENSES"
    licenses.mkdir(parents=True)
    (source / "LICENSE").write_text("root terms\n", encoding="utf-8")
    (source / "pyproject.toml").write_text(
        '[project]\nname = "sceneio"\nversion = "0.2.0"\n',
        encoding="utf-8",
    )
    (licenses / "README.md").write_text(
        "# Notices\n\n[one](one.txt), [root](../LICENSE)\n",
        encoding="utf-8",
    )
    (licenses / "one.txt").write_text("notice\n", encoding="utf-8")
    package = source / "src" / "sceneio"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    provenance = source / "src" / "cpp" / "third_party" / "project"
    provenance.mkdir(parents=True)
    (provenance / "COMMIT.txt").write_text("revision\n", encoding="utf-8")
    return source


def _source_files(source: Path) -> tuple[str, ...]:
    return tuple(
        path.relative_to(source).as_posix()
        for path in sorted(item for item in source.rglob("*") if item.is_file())
    )


def test_runtime_source_assets_allow_only_exact_openvdb_seed_paths(tmp_path):
    source = _source_root(tmp_path)
    assets = source / "src" / "sceneio" / "io" / "_assets"
    assets.mkdir(parents=True)
    provenance = assets / "openvdb_float_template.PROVENANCE.txt"
    seed = assets / "openvdb_float_template.vdb"
    provenance.write_bytes(b"pinned provenance")
    seed.write_bytes(b"VDB seed")

    result = VERIFIER._runtime_source_assets(source)

    assert result[
        "sceneio/io/_assets/openvdb_float_template.PROVENANCE.txt"
    ] == b"pinned provenance"
    assert result["sceneio/io/_assets/openvdb_float_template.vdb"] == b"VDB seed"

    (assets / "unlisted.txt").write_text("not declared", encoding="utf-8")
    with pytest.raises(ValueError, match="undeclared source-package asset"):
        VERIFIER._runtime_source_assets(source)


def _sdist(
    tmp_path: Path,
    source: Path,
    *,
    omit: frozenset[str] = frozenset(),
) -> Path:
    path = tmp_path / "sceneio-0.2.0.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for relative in _source_files(source):
            if relative in omit:
                continue
            payload = (source / relative).read_bytes()
            info = tarfile.TarInfo(f"sceneio-0.2.0/{relative}")
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
        package_info = b"Metadata-Version: 2.4\nName: sceneio\nVersion: 0.2.0\n"
        info = tarfile.TarInfo("sceneio-0.2.0/PKG-INFO")
        info.size = len(package_info)
        archive.addfile(info, io.BytesIO(package_info))
    return path


def _wheel(
    tmp_path: Path,
    source: Path,
    *,
    wheel_name: str = "sceneio-0.2.0-cp312-abi3-win_amd64.whl",
    runtime_requirements: tuple[str, ...] = ("numpy>=1.26",),
    core_member: str = WINDOWS_CORE,
    metadata_name: str = "sceneio",
    metadata_version: str = "0.2.0",
    wheel_tags: tuple[str, ...] | None = None,
    root_is_purelib: str = "false",
    package_payload: bytes | None = None,
    extra_member: str | None = None,
    extra_payload: bytes = b"\0",
    delvewheel_metadata: bytes | None = None,
) -> Path:
    path = tmp_path / wheel_name
    dist_info = "sceneio-0.2.0.dist-info"
    if wheel_tags is None:
        python_tag, abi_tag, platform_tag = wheel_name[:-4].rsplit("-", 3)[-3:]
        wheel_tags = tuple(
            f"{python_tag}-{abi_tag}-{tag}"
            for tag in platform_tag.split(".")
        )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "sceneio/__init__.py",
            package_payload
            if package_payload is not None
            else (source / "src" / "sceneio" / "__init__.py").read_bytes(),
        )
        archive.writestr(core_member, b"extension")
        requirements = "".join(
            f"Requires-Dist: {requirement}\n"
            for requirement in runtime_requirements
        )
        archive.writestr(
            f"{dist_info}/METADATA",
            f"Metadata-Version: 2.4\nName: {metadata_name}\n"
            f"Version: {metadata_version}\n"
            f"{requirements}"
            "Requires-Dist: pytest>=8; extra == 'test'\n"
            'Requires-Dist: ruff; extra == "dev"\n',
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\n"
            f"Root-Is-Purelib: {root_is_purelib}\n"
            + "".join(f"Tag: {tag}\n" for tag in wheel_tags),
        )
        archive.writestr(f"{dist_info}/RECORD", "")
        for relative in ("LICENSE", "LICENSES/README.md", "LICENSES/one.txt"):
            archive.writestr(
                f"{dist_info}/licenses/{relative}",
                (source / relative).read_bytes(),
            )
        if extra_member is not None:
            archive.writestr(extra_member, extra_payload)
        if delvewheel_metadata is not None:
            archive.writestr(
                f"{dist_info}/DELVEWHEEL",
                delvewheel_metadata,
            )
    return path


def test_distribution_verifier_accepts_expected_inventory(tmp_path: Path) -> None:
    source = _source_root(tmp_path)
    sdist = _sdist(tmp_path, source)
    wheel = _wheel(tmp_path, source)
    report = VERIFIER.verify_distributions(
        source,
        sdist,
        [wheel],
        _source_files(source),
    )

    assert report["source_distribution"]["license_assets"] == 3
    assert report["wheels"][0]["native_members"] == [
        WINDOWS_CORE
    ]
    assert report["wheels"][0]["runtime_requirements"] == ["numpy>=1.26"]
    assert report["wheels"][0]["runtime_files"] == 1
    assert report["source_closure"]["expected_files"] == len(_source_files(source))
    assert report["source_closure"]["generated_files"] == ["PKG-INFO"]

    (source / "LICENSES" / "one.txt").write_text(
        "changed notice\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="source distribution license asset differs"):
        VERIFIER.verify_distributions(source, sdist, [wheel])

    updated_sdist = _sdist(tmp_path, source)
    with pytest.raises(ValueError, match=r"\.whl license asset differs"):
        VERIFIER.verify_distributions(source, updated_sdist, [wheel])


@pytest.mark.parametrize(
    ("wheel_name", "core_member"),
    [
        pytest.param(
            "sceneio-0.2.0-cp312-abi3-win_amd64.whl",
            "sceneio/_core.pyd",
            id="windows",
        ),
        pytest.param(
            "sceneio-0.2.0-cp312-abi3-"
            "manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
            "sceneio/_core.abi3.so",
            id="manylinux",
        ),
        pytest.param(
            "sceneio-0.2.0-cp312-abi3-"
            "manylinux2014_x86_64.manylinux_2_17_x86_64.whl",
            "sceneio/_core.abi3.so",
            id="manylinux-repaired-order",
        ),
        pytest.param(
            "sceneio-0.2.0-cp312-abi3-macosx_11_0_arm64.whl",
            "sceneio/_core.abi3.so",
            id="macos",
        ),
    ],
)
def test_distribution_verifier_accepts_platform_stable_abi_member(
    tmp_path: Path,
    wheel_name: str,
    core_member: str,
) -> None:
    source = _source_root(tmp_path)
    report = VERIFIER.verify_distributions(
        source,
        _sdist(tmp_path, source),
        [
            _wheel(
                tmp_path,
                source,
                wheel_name=wheel_name,
                core_member=core_member,
            )
        ],
    )
    assert report["wheels"][0]["native_members"] == [core_member]


@pytest.mark.parametrize(
    "runtime_basename",
    ["concrt140", "msvcp140", "vcruntime140", "vcruntime140_1"],
)
def test_distribution_verifier_accepts_repaired_msvc_runtime(
    tmp_path: Path,
    runtime_basename: str,
) -> None:
    source = _source_root(tmp_path)
    package = source / "src" / "sceneio" / "__init__.py"
    original, patched = _delvewheel_fixture()
    package.write_bytes(original)
    runtime = f"sceneio.libs/{runtime_basename}.dll"
    report = VERIFIER.verify_distributions(
        source,
        _sdist(tmp_path, source),
        [
            _wheel(
                tmp_path,
                source,
                **_complete_delvewheel_payload(
                    patched,
                    runtime=runtime,
                ),
            )
        ],
    )
    assert report["wheels"][0]["native_members"] == [runtime, WINDOWS_CORE]


def test_distribution_verifier_accepts_delvewheel_metadata(
    tmp_path: Path,
) -> None:
    source = _source_root(tmp_path)
    package = source / "src" / "sceneio" / "__init__.py"
    original, patched = _delvewheel_fixture()
    package.write_bytes(original)
    report = VERIFIER.verify_distributions(
        source,
        _sdist(tmp_path, source),
        [
            _wheel(
                tmp_path,
                source,
                **_complete_delvewheel_payload(patched),
            )
        ],
    )
    assert report["wheels"][0]["platform"] == "windows"


@pytest.mark.parametrize(
    ("wheel_name", "core_member", "payload"),
    [
        pytest.param(
            "sceneio-0.2.0-cp312-abi3-win_amd64.whl",
            WINDOWS_CORE,
            b"Version: 1.12.0\nArguments: []\n",
            id="wrong-version",
        ),
        pytest.param(
            "sceneio-0.2.0-cp312-abi3-win_amd64.whl",
            WINDOWS_CORE,
            b"Version: 1.13.0\nArguments: ['tool', 'show']\n",
            id="wrong-command",
        ),
        pytest.param(
            "sceneio-0.2.0-cp312-abi3-"
            "manylinux2014_x86_64.manylinux_2_17_x86_64.whl",
            "sceneio/_core.abi3.so",
            DELVEWHEEL_METADATA,
            id="non-windows",
        ),
    ],
)
def test_distribution_verifier_rejects_invalid_delvewheel_metadata(
    tmp_path: Path,
    wheel_name: str,
    core_member: str,
    payload: bytes,
) -> None:
    source = _source_root(tmp_path)
    with pytest.raises(ValueError, match="invalid delvewheel metadata"):
        VERIFIER.verify_distributions(
            source,
            _sdist(tmp_path, source),
            [
                _wheel(
                    tmp_path,
                    source,
                    wheel_name=wheel_name,
                    core_member=core_member,
                    delvewheel_metadata=payload,
                )
            ],
        )


@pytest.mark.parametrize("component", ["runtime", "bootstrap", "metadata"])
def test_distribution_verifier_rejects_incomplete_delvewheel_repair(
    tmp_path: Path,
    component: str,
) -> None:
    source = _source_root(tmp_path)
    package = source / "src" / "sceneio" / "__init__.py"
    original, patched = _delvewheel_fixture()
    package.write_bytes(original)
    kwargs: dict[str, object] = {}
    if component == "runtime":
        kwargs.update(
            extra_member="sceneio.libs/msvcp140.dll",
            extra_payload=b"MZruntime",
        )
    elif component == "bootstrap":
        kwargs["package_payload"] = patched
    else:
        kwargs["delvewheel_metadata"] = DELVEWHEEL_METADATA

    with pytest.raises(ValueError, match="incomplete delvewheel repair payload"):
        VERIFIER.verify_distributions(
            source,
            _sdist(tmp_path, source),
            [_wheel(tmp_path, source, **kwargs)],
        )


@pytest.mark.parametrize(
    "runtime",
    [
        "sceneio.libs/other-dependency.dll",
        "sceneio.libs/msvcp999.dll",
        "sceneio.libs/msvcp140-deadbeef.dll",
    ],
)
def test_distribution_verifier_rejects_unrecognized_repaired_library(
    tmp_path: Path,
    runtime: str,
) -> None:
    source = _source_root(tmp_path)
    with pytest.raises(ValueError, match="permitted repaired runtime libraries"):
        VERIFIER.verify_distributions(
            source,
            _sdist(tmp_path, source),
            [
                _wheel(
                    tmp_path,
                    source,
                    extra_member=runtime,
                    extra_payload=b"MZlibrary",
                )
            ],
        )


def test_distribution_verifier_rejects_repaired_runtime_on_manylinux(
    tmp_path: Path,
) -> None:
    source = _source_root(tmp_path)
    with pytest.raises(ValueError, match="permitted repaired runtime libraries"):
        VERIFIER.verify_distributions(
            source,
            _sdist(tmp_path, source),
            [
                _wheel(
                    tmp_path,
                    source,
                    wheel_name=(
                        "sceneio-0.2.0-cp312-abi3-"
                        "manylinux2014_x86_64.manylinux_2_17_x86_64.whl"
                    ),
                    core_member="sceneio/_core.abi3.so",
                    extra_member="sceneio.libs/msvcp140.dll",
                    extra_payload=b"MZruntime",
                )
            ],
        )


def test_distribution_verifier_requires_core_with_repaired_runtime(
    tmp_path: Path,
) -> None:
    source = _source_root(tmp_path)
    runtime = "sceneio.libs/msvcp140.dll"
    with pytest.raises(ValueError, match=r"exactly sceneio/_core\.pyd"):
        VERIFIER.verify_distributions(
            source,
            _sdist(tmp_path, source),
            [_wheel(tmp_path, source, core_member=runtime)],
        )


def test_distribution_verifier_rejects_duplicate_core_member(
    tmp_path: Path,
) -> None:
    source = _source_root(tmp_path)
    with pytest.warns(UserWarning, match="Duplicate name"):
        wheel = _wheel(
            tmp_path,
            source,
            extra_member=WINDOWS_CORE,
            extra_payload=b"MZduplicate",
        )
    with pytest.raises(ValueError, match="contains duplicate members"):
        VERIFIER.verify_distributions(
            source,
            _sdist(tmp_path, source),
            [wheel],
        )


def test_distribution_verifier_accepts_exact_delvewheel_runtime_patch(
    tmp_path: Path,
) -> None:
    source = _source_root(tmp_path)
    package = source / "src" / "sceneio" / "__init__.py"
    original, patched = _delvewheel_fixture()
    package.write_bytes(original)
    report = VERIFIER.verify_distributions(
        source,
        _sdist(tmp_path, source),
        [
            _wheel(
                tmp_path,
                source,
                **_complete_delvewheel_payload(patched),
            )
        ],
    )
    assert report["wheels"][0]["runtime_files"] == 1


@pytest.mark.parametrize(
    "newline",
    [b"\r\n", b"\r"],
    ids=["crlf", "cr"],
)
def test_distribution_verifier_accepts_delvewheel_patch_line_endings(
    tmp_path: Path,
    newline: bytes,
) -> None:
    source = _source_root(tmp_path)
    package = source / "src" / "sceneio" / "__init__.py"
    original, patched = _delvewheel_fixture(newline)
    package.write_bytes(original)
    VERIFIER.verify_distributions(
        source,
        _sdist(tmp_path, source),
        [
            _wheel(
                tmp_path,
                source,
                **_complete_delvewheel_payload(patched),
            )
        ],
    )


def test_distribution_verifier_uses_first_source_line_ending_for_patch(
    tmp_path: Path,
) -> None:
    source = _source_root(tmp_path)
    package = source / "src" / "sceneio" / "__init__.py"
    original = (
        b'"""sceneio package."""\n\n'
        b"from __future__ import annotations\n\r\n"
        b"VALUE = 1\r\n"
    )
    patched = (
        b'"""sceneio package."""\n\n'
        b"from __future__ import annotations\n\n\n"
        + DELVEWHEEL_PATCH
        + b"\nVALUE = 1\r\n"
    )
    package.write_bytes(original)
    VERIFIER.verify_distributions(
        source,
        _sdist(tmp_path, source),
        [
            _wheel(
                tmp_path,
                source,
                **_complete_delvewheel_payload(patched),
            )
        ],
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "patch-version",
        "repository-prefix",
        "repository-suffix",
        "duplicate-marker",
        "wrong-placement",
    ],
)
def test_distribution_verifier_rejects_modified_delvewheel_runtime_patch(
    tmp_path: Path,
    mutation: str,
) -> None:
    source = _source_root(tmp_path)
    package = source / "src" / "sceneio" / "__init__.py"
    original, patched = _delvewheel_fixture()
    package.write_bytes(original)
    if mutation == "patch-version":
        patched = patched.replace(b"_1_13_0", b"_1_13_1")
    elif mutation == "repository-prefix":
        patched = patched.replace(b"sceneio package", b"changed package")
    elif mutation == "repository-suffix":
        patched = patched.replace(b"VALUE = 1", b"VALUE = 2")
    elif mutation == "duplicate-marker":
        patched = patched.replace(
            b"# start delvewheel patch",
            b"# start delvewheel patch\n# start delvewheel patch",
            1,
        )
    else:
        patched = DELVEWHEEL_PATCH + b"\n" + original
    with pytest.raises(ValueError, match="runtime file differs"):
        VERIFIER.verify_distributions(
            source,
            _sdist(tmp_path, source),
            [
                _wheel(
                    tmp_path,
                    source,
                    **_complete_delvewheel_payload(patched),
                )
            ],
        )


def test_distribution_verifier_rejects_delvewheel_patch_off_windows(
    tmp_path: Path,
) -> None:
    source = _source_root(tmp_path)
    package = source / "src" / "sceneio" / "__init__.py"
    original, patched = _delvewheel_fixture()
    package.write_bytes(original)
    with pytest.raises(ValueError, match="runtime file differs"):
        VERIFIER.verify_distributions(
            source,
            _sdist(tmp_path, source),
            [
                _wheel(
                    tmp_path,
                    source,
                    wheel_name=(
                        "sceneio-0.2.0-cp312-abi3-"
                        "manylinux2014_x86_64.manylinux_2_17_x86_64.whl"
                    ),
                    core_member="sceneio/_core.abi3.so",
                    package_payload=patched,
                )
            ],
        )


def test_distribution_verifier_rejects_delvewheel_patch_in_other_module(
    tmp_path: Path,
) -> None:
    source = _source_root(tmp_path)
    original, patched = _delvewheel_fixture()
    helper = source / "src" / "sceneio" / "helper.py"
    helper.write_bytes(original)
    with pytest.raises(ValueError, match="runtime file differs"):
        VERIFIER.verify_distributions(
            source,
            _sdist(tmp_path, source),
            [
                _wheel(
                    tmp_path,
                    source,
                    extra_member="sceneio/helper.py",
                    extra_payload=patched,
                )
            ],
        )


@pytest.mark.parametrize(
    ("wheel_name", "core_member"),
    [
        pytest.param(
            "sceneio-0.2.0-cp312-abi3-win_amd64.whl",
            "sceneio/_core.cp312-win_amd64.pyd",
            id="windows-cpython-specific",
        ),
        pytest.param(
            "sceneio-0.2.0-cp312-abi3-"
            "manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
            "sceneio/_core.cpython-312-x86_64-linux-gnu.so",
            id="linux-cpython-specific",
        ),
    ],
)
def test_distribution_verifier_rejects_cpython_specific_core_in_abi3_wheel(
    tmp_path: Path,
    wheel_name: str,
    core_member: str,
) -> None:
    source = _source_root(tmp_path)
    with pytest.raises(ValueError, match="must contain exactly"):
        VERIFIER.verify_distributions(
            source,
            _sdist(tmp_path, source),
            [
                _wheel(
                    tmp_path,
                    source,
                    wheel_name=wheel_name,
                    core_member=core_member,
                )
            ],
        )


@pytest.mark.parametrize(
    "wheel_name",
    [
        pytest.param(
            "sceneio-0.2.0-cp312-cp312-win_amd64.whl",
            id="cpython-abi",
        ),
        pytest.param(
            "sceneio-0.2.0-cp311-abi3-win_amd64.whl",
            id="older-python",
        ),
        pytest.param(
            "sceneio-0.2.0-py3-none-win_amd64.whl",
            id="pure-python",
        ),
        pytest.param(
            "sceneio-0.2.0-cp312-cp312-"
            "manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
            id="linux-cpython-abi",
        ),
        pytest.param(
            "other-0.2.0-cp312-abi3-win_amd64.whl",
            id="wrong-distribution",
        ),
        pytest.param(
            "sceneio-9.9.9-cp312-abi3-win_amd64.whl",
            id="wrong-version",
        ),
    ],
)
def test_distribution_verifier_rejects_wrong_wheel_filename_contract(
    tmp_path: Path,
    wheel_name: str,
) -> None:
    source = _source_root(tmp_path)
    with pytest.raises(ValueError, match="must target"):
        VERIFIER.verify_distributions(
            source,
            _sdist(tmp_path, source),
            [_wheel(tmp_path, source, wheel_name=wheel_name)],
        )


def test_distribution_verifier_rejects_filename_and_wheel_tag_mismatch(
    tmp_path: Path,
) -> None:
    source = _source_root(tmp_path)
    with pytest.raises(ValueError, match="WHEEL tags must match"):
        VERIFIER.verify_distributions(
            source,
            _sdist(tmp_path, source),
            [
                _wheel(
                    tmp_path,
                    source,
                    wheel_tags=("cp312-cp312-win_amd64",),
                )
            ],
        )


def test_distribution_verifier_rejects_purelib_native_wheel(
    tmp_path: Path,
) -> None:
    source = _source_root(tmp_path)
    with pytest.raises(ValueError, match="Root-Is-Purelib: false"):
        VERIFIER.verify_distributions(
            source,
            _sdist(tmp_path, source),
            [_wheel(tmp_path, source, root_is_purelib="true")],
        )


@pytest.mark.parametrize(
    ("metadata_name", "metadata_version"),
    [
        pytest.param("other", "0.2.0", id="name"),
        pytest.param("sceneio", "9.9.9", id="version"),
    ],
)
def test_distribution_verifier_rejects_metadata_identity_mismatch(
    tmp_path: Path,
    metadata_name: str,
    metadata_version: str,
) -> None:
    source = _source_root(tmp_path)
    with pytest.raises(ValueError, match="METADATA identity"):
        VERIFIER.verify_distributions(
            source,
            _sdist(tmp_path, source),
            [
                _wheel(
                    tmp_path,
                    source,
                    metadata_name=metadata_name,
                    metadata_version=metadata_version,
                )
            ],
        )


@pytest.mark.parametrize(
    ("wheel_kwargs", "message"),
    [
        pytest.param(
            {"metadata_name": "sceneio\nName: other"},
            "METADATA identity",
            id="duplicate-name",
        ),
        pytest.param(
            {"metadata_version": "0.2.0\nVersion: 9.9.9"},
            "METADATA identity",
            id="duplicate-version",
        ),
        pytest.param(
            {"root_is_purelib": "false\nRoot-Is-Purelib: true"},
            "Root-Is-Purelib: false once",
            id="duplicate-purelib",
        ),
    ],
)
def test_distribution_verifier_rejects_contradictory_duplicate_headers(
    tmp_path: Path,
    wheel_kwargs: dict[str, str],
    message: str,
) -> None:
    source = _source_root(tmp_path)
    with pytest.raises(ValueError, match=message):
        VERIFIER.verify_distributions(
            source,
            _sdist(tmp_path, source),
            [_wheel(tmp_path, source, **wheel_kwargs)],
        )


def test_distribution_verifier_requires_exact_combined_platform_matrix(
    tmp_path: Path,
) -> None:
    source = _source_root(tmp_path)
    sdist = _sdist(tmp_path, source)
    windows = _wheel(tmp_path, source)
    manylinux = _wheel(
        tmp_path,
        source,
        wheel_name=(
            "sceneio-0.2.0-cp312-abi3-"
            "manylinux_2_17_x86_64.manylinux2014_x86_64.whl"
        ),
        core_member="sceneio/_core.abi3.so",
    )
    macos = _wheel(
        tmp_path,
        source,
        wheel_name="sceneio-0.2.0-cp312-abi3-macosx_11_0_arm64.whl",
        core_member="sceneio/_core.abi3.so",
    )

    report = VERIFIER.verify_distributions(
        source,
        sdist,
        [windows, manylinux, macos],
        require_exact_wheel_matrix=True,
    )
    assert sorted(item["platform"] for item in report["wheels"]) == [
        "macos",
        "manylinux",
        "windows",
    ]
    with pytest.raises(ValueError, match="exact three-platform matrix"):
        VERIFIER.verify_distributions(
            source,
            sdist,
            [windows, manylinux],
            require_exact_wheel_matrix=True,
        )
    with pytest.raises(ValueError, match="exact three-platform matrix"):
        VERIFIER.verify_distributions(
            source,
            sdist,
            [windows, windows, macos],
            require_exact_wheel_matrix=True,
        )


def test_distribution_verifier_exact_matrix_mode_rejects_singleton(
    tmp_path: Path,
) -> None:
    source = _source_root(tmp_path)
    sdist = _sdist(tmp_path, source)
    windows = _wheel(tmp_path, source)

    report = VERIFIER.verify_distributions(source, sdist, [windows])
    assert [item["platform"] for item in report["wheels"]] == ["windows"]

    with pytest.raises(ValueError, match="exact three-platform matrix"):
        VERIFIER.verify_distributions(
            source,
            sdist,
            [windows],
            require_exact_wheel_matrix=True,
        )


@pytest.mark.parametrize(
    "runtime_requirements",
    [
        pytest.param((), id="missing"),
        pytest.param(("another-package>=1",), id="other-base"),
        pytest.param(
            ("numpy>=1.26; python_version >= '3.12'",),
            id="conditional-numpy",
        ),
        pytest.param(("numpy>=1.26; extra == 'test'",), id="extra-only-numpy"),
        pytest.param(
            ("numpy>=1.26", "another-package; sys_platform == 'win32'"),
            id="platform-package",
        ),
        pytest.param(("numpy[dev]>=1.26",), id="numpy-extra"),
        pytest.param(
            (
                "numpy>=1.26",
                'another-package; sys_platform == "win32" or extra == "test"',
            ),
            id="platform-or-extra",
        ),
        pytest.param(
            (
                "numpy>=1.26",
                'another-package; extra == "test" or python_version >= "3.12"',
            ),
            id="extra-or-python",
        ),
        pytest.param(
            (
                "numpy>=1.26",
                'another-package; (extra == "test") or sys_platform == "win32"',
            ),
            id="parenthesized-extra-or-platform",
        ),
    ],
)
def test_distribution_verifier_requires_unconditional_numpy_only(
    tmp_path: Path,
    runtime_requirements: tuple[str, ...],
) -> None:
    source = _source_root(tmp_path)
    with pytest.raises(ValueError, match="unconditional NumPy"):
        VERIFIER.verify_distributions(
            source,
            _sdist(tmp_path, source),
            [_wheel(tmp_path, source, runtime_requirements=runtime_requirements)],
        )


@pytest.mark.parametrize(
    ("core_member", "extra_member", "extra_payload", "message"),
    [
        pytest.param(
            WINDOWS_CORE,
            "sceneio/extra.dll",
            b"\0",
            "must contain exactly",
            id="extra-dll",
        ),
        pytest.param(
            WINDOWS_CORE,
            "sceneio/libunexpected.so.1",
            b"\0",
            "must contain exactly",
            id="versioned-so",
        ),
        pytest.param(
            WINDOWS_CORE,
            "sceneio/bin/ffmpeg.exe",
            b"\0",
            "must contain exactly",
            id="extra-executable",
        ),
        pytest.param(
            WINDOWS_CORE,
            "sceneio/bin/ffmpeg",
            b"\0",
            "unexpected wheel payload",
            id="extensionless-executable",
        ),
        pytest.param(
            WINDOWS_CORE,
            "sceneio/lib/cmake/toolchain.cmake",
            b"\0",
            "unexpected wheel payload",
            id="cmake",
        ),
        pytest.param(
            WINDOWS_CORE,
            "build/temp.o",
            b"\0",
            "unexpected wheel payload",
            id="object-file",
        ),
        pytest.param(
            WINDOWS_CORE,
            "evil/arbitrary.payload",
            b"\0",
            "unexpected wheel payload",
            id="unknown-root",
        ),
        pytest.param(
            WINDOWS_CORE,
            "sceneio/native.bin",
            b"\x7fELF",
            "must contain exactly",
            id="native-magic",
        ),
        pytest.param(
            "sceneio/_core.ffmpeg.exe",
            None,
            b"\0",
            "must contain exactly",
            id="core-executable",
        ),
        pytest.param(
            "sceneio/_core.libfoo.so.1",
            None,
            b"\0",
            "must contain exactly",
            id="core-versioned-so",
        ),
        pytest.param(
            "sceneio/_core.foo.dll",
            None,
            b"\0",
            "must contain exactly",
            id="core-dll",
        ),
    ],
)
def test_distribution_verifier_rejects_unexpected_wheel_payload(
    tmp_path: Path,
    core_member: str,
    extra_member: str | None,
    extra_payload: bytes,
    message: str,
) -> None:
    source = _source_root(tmp_path)
    with pytest.raises(ValueError, match=message):
        VERIFIER.verify_distributions(
            source,
            _sdist(tmp_path, source),
            [
                _wheel(
                    tmp_path,
                    source,
                    core_member=core_member,
                    extra_member=extra_member,
                    extra_payload=extra_payload,
                )
            ],
        )


def test_distribution_verifier_rejects_repository_to_sdist_drift(
    tmp_path: Path,
) -> None:
    source = _source_root(tmp_path)
    expected_files = _source_files(source)
    provenance = "src/cpp/third_party/project/COMMIT.txt"
    missing = _sdist(tmp_path, source, omit=frozenset({provenance}))
    with pytest.raises(ValueError, match="source closure is missing"):
        VERIFIER.verify_distributions(source, missing, [], expected_files)

    complete = _sdist(tmp_path, source)
    (source / provenance).write_text("different revision\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source file differs"):
        VERIFIER.verify_distributions(source, complete, [], expected_files)


def test_r6_wheelhouse_lock_is_exact_and_cross_platform() -> None:
    lock = (ROOT / "tools" / "r6-wheelhouse.lock").read_text(encoding="utf-8")
    pins = re.findall(r"^([A-Za-z0-9-]+)==([0-9.]+)", lock, re.MULTILINE)
    hashes = re.findall(r"--hash=sha256:([0-9a-f]{64})", lock)

    assert pins == [
        ("scikit-build-core", "1.0.3"),
        ("nanobind", "2.13.0"),
        ("packaging", "26.2"),
        ("pathspec", "1.1.1"),
        ("numpy", "2.2.6"),
    ]
    assert len(hashes) == 7
    assert len(hashes) == len(set(hashes))


def _assert_exact_matrix_and_combined_inventory(workflow: str) -> None:
    wheel_job = workflow.split("\n  wheels:\n", 1)[1].split(
        "\n  distribution-inventory:\n", 1
    )[0]
    combined_job = workflow.split("\n  distribution-inventory:\n", 1)[1].split(
        "\n  publish:\n", 1
    )[0]
    assert wheel_job.count("\n          - label: ") == 3
    assert combined_job.count("tools/verify_distribution.py") == 1
    assert '--source-root "$package_dir"' in combined_job
    assert '--sdist "${{ steps.source.outputs.sdist-path }}"' in combined_job
    assert "--wheel-dir wheelhouse" in combined_job
    assert "--require-exact-wheel-matrix" not in wheel_job
    assert "--require-exact-wheel-matrix" in combined_job
    assert "--output distribution-inventory.json" in combined_job


def test_publish_workflow_builds_every_wheel_from_the_exact_sdist() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )
    wheel_job = workflow.split("\n  wheels:\n", 1)[1].split(
        "\n  distribution-inventory:\n", 1
    )[0]
    publish_job = workflow.split("\n  publish:\n", 1)[1]
    sdist_job = workflow.split("\n  sdist:\n", 1)[1].split("\n  wheels:\n", 1)[0]
    combined_job = workflow.split("\n  distribution-inventory:\n", 1)[1].split(
        "\n  publish:\n", 1
    )[0]

    assert 'version: "0.8.6"' in sdist_job
    assert '--dest "$RUNNER_TEMP/r6-build-wheelhouse"' in sdist_job
    assert 'uv venv "$RUNNER_TEMP/r6-build-env"' in sdist_job
    assert '--python "$RUNNER_TEMP/r6-build-env/bin/python"' in sdist_job
    assert '--find-links "$RUNNER_TEMP/r6-build-wheelhouse"' in sdist_job
    assert "--dest build-wheelhouse" not in sdist_job
    assert "--python .venv/bin/python" not in sdist_job
    assert "--source-root ." in sdist_job
    assert "--require-git-source-closure" in sdist_job
    assert "--output source-inventory.json" in sdist_job
    assert "name: source-inventory" in sdist_job
    assert "needs: sdist" in wheel_job
    assert "name: sdist" in wheel_job
    assert "EXPECTED_SHA256: ${{ needs.sdist.outputs.sha256 }}" in wheel_job
    assert "tar -xzf \"$sdist\" -C build/sdist-source" in wheel_job
    assert "package-dir: ${{ steps.source.outputs.package-dir }}" in wheel_job
    assert "actions/checkout" not in wheel_job
    assert "pypa/cibuildwheel@v4.1.0" in wheel_job
    assert (
        'CIBW_BUILD_FRONTEND: "pip; args: --no-build-isolation --no-index"'
        in wheel_job
    )
    before_build = wheel_job.split("CIBW_BEFORE_BUILD:", maxsplit=1)[1].split(
        "CIBW_BEFORE_TEST:", maxsplit=1
    )[0]
    before_test = wheel_job.split("CIBW_BEFORE_TEST:", maxsplit=1)[1].split(
        "CIBW_TEST_REQUIRES:", maxsplit=1
    )[0]
    for install_hook in (before_build, before_test):
        assert "--no-index" in install_hook
        assert "--find-links {package}/.build-wheelhouse" in install_hook
    assert "PIP_NO_INDEX=1" not in wheel_job
    repair_command = wheel_job.split(
        "CIBW_REPAIR_WHEEL_COMMAND_WINDOWS:", maxsplit=1
    )[1].split("CIBW_ENVIRONMENT:", maxsplit=1)[0]
    assert [line.strip() for line in repair_command.strip().splitlines()] == [
        ">-",
        'python "{package}/tools/repair_windows_wheel.py"',
        '--wheel "{wheel}"',
        '--dest-dir "{dest_dir}"',
    ]
    assert "FETCHCONTENT_FULLY_DISCONNECTED=ON" in wheel_job
    assert "--require-hashes" in wheel_job
    for row in (
        "- label: manylinux2014-gcc10-x86_64\n"
        "            os: ubuntu-24.04\n"
        "            arch: x86_64",
        "- label: windows-msvc-amd64\n"
        "            os: windows-2022\n"
        "            arch: AMD64",
        "- label: macos-appleclang-arm64\n"
        "            os: macos-15\n"
        "            arch: arm64",
    ):
        assert row in wheel_job
    assert "CIBW_ARCHS: ${{ matrix.arch }}" in wheel_job
    assert "CIBW_MANYLINUX_X86_64_IMAGE:" in wheel_job
    assert "numpy==2.2.6" in wheel_job
    assert 'CIBW_TEST_REQUIRES: ""' in wheel_job
    assert "name: Smoke installed TinyUSDZ profile" in wheel_job
    assert 'python -m venv "$smoke_env"' in wheel_job
    assert '"$RUNNER_OS" == "Windows"' in wheel_job
    assert '"${wheel}[usd]"' in wheel_job
    assert "--only-binary=:all:" in wheel_job
    assert "numpy==2.2.6 tinyusdz==0.9.4" in wheel_job
    assert 'sceneio.capabilities("usd").available' in wheel_job
    assert '"$smoke_python" -I -m sceneio._wheel_smoke' in wheel_job
    assert wheel_job.count("tools/verify_distribution.py") == 1
    assert '--sdist "${{ steps.source.outputs.sdist-path }}"' in wheel_job
    assert "--wheel-dir wheelhouse" in wheel_job
    assert 'needs: [sdist, wheels]' in combined_job
    assert "--wheel-dir wheelhouse" in combined_job
    assert "python -m sceneio._wheel_smoke" in (
        ROOT / "pyproject.toml"
    ).read_text(encoding="utf-8")

    assert "needs: [sdist, wheels, distribution-inventory]" in publish_job
    assert (
        "if: github.event_name == 'push' && "
        "startsWith(github.ref, 'refs/tags/v')" in publish_job
    )

    _assert_exact_matrix_and_combined_inventory(workflow)
    extra_row = workflow.replace(
        "            arch: arm64",
        "            arch: arm64\n"
        "          - label: unexpected\n"
        "            os: ubuntu-24.04\n"
        "            arch: x86_64",
        1,
    )
    with pytest.raises(AssertionError):
        _assert_exact_matrix_and_combined_inventory(extra_row)

    head, separator, combined_tail = workflow.partition(
        "\n  distribution-inventory:\n"
    )
    fake_combined = head + separator + combined_tail.replace(
        'python "$package_dir/tools/verify_distribution.py"',
        "python fake_inventory.py",
        1,
    )
    with pytest.raises(AssertionError):
        _assert_exact_matrix_and_combined_inventory(fake_combined)
