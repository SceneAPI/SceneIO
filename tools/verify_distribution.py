"""Verify the source and wheel inventory used by the release workflow.

The checker intentionally uses only the Python standard library so it can run
before SceneIO or any optional test package is installed.
"""

from __future__ import annotations

import argparse
import ast
import email
import hashlib
import json
import re
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple

GENERATED_SDIST_FILES = frozenset({"PKG-INFO"})
WHEEL_METADATA_FILES = frozenset({"METADATA", "RECORD", "WHEEL"})
RUNTIME_SOURCE_SUFFIXES = frozenset({".py", ".pyi"})
RUNTIME_SOURCE_NAMES = frozenset({"py.typed"})
NATIVE_NAME_PATTERN = re.compile(
    r"(?:\.(?:dll|exe|pyd)|\.so(?:\.\d+)*|(?:\.\d+)*\.dylib)$",
    re.IGNORECASE,
)
NATIVE_MAGICS = (
    b"\x00asm",
    b"\x7fELF",
    b"!<arch>\n",
    b"MZ",
    b"\xca\xfe\xba\xbe",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
)
EXTRA_MARKER_PATTERN = re.compile(
    r"\bextra\s*==\s*(?P<quote>['\"])[A-Za-z0-9_.-]+(?P=quote)",
    re.IGNORECASE,
)
EXPECTED_RUNTIME_REQUIREMENTS = ["numpy>=1.26"]
MANYLINUX_METADATA_TAGS = (
    "cp312-abi3-manylinux2014_x86_64",
    "cp312-abi3-manylinux_2_17_x86_64",
)
MANYLINUX_WHEEL_CONTRACT = (
    "manylinux",
    MANYLINUX_METADATA_TAGS,
    "sceneio/_core.abi3.so",
)
EXPECTED_WHEEL_PLATFORM_TAGS = {
    "win_amd64": (
        "windows",
        ("cp312-abi3-win_amd64",),
        "sceneio/_core.pyd",
    ),
    "manylinux_2_17_x86_64.manylinux2014_x86_64": MANYLINUX_WHEEL_CONTRACT,
    "manylinux2014_x86_64.manylinux_2_17_x86_64": MANYLINUX_WHEEL_CONTRACT,
    "macosx_11_0_arm64": (
        "macos",
        ("cp312-abi3-macosx_11_0_arm64",),
        "sceneio/_core.abi3.so",
    ),
}
WINDOWS_REPAIRED_LIBRARY_PATTERN = re.compile(
    r"sceneio\.libs/"
    r"(?:concrt140|msvcp140|vcruntime140|vcruntime140_1)\.dll",
    re.IGNORECASE,
)
DELVEWHEEL_1_13_0_PATCH_SHA256 = (
    "440f1b34ba0f7c77aff4752249937d9da601d1a1bf596ecec40021a153afc74f"
)
DELVEWHEEL_VERSION = "1.13.0"


class WheelContract(NamedTuple):
    platform: str
    metadata_tags: tuple[str, ...]
    core_member: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _indexed_license_files(source_root: Path) -> tuple[str, ...]:
    index_path = source_root / "LICENSES" / "README.md"
    index = index_path.read_text(encoding="utf-8")
    linked_notices = (
        target
        for target in re.findall(r"\]\(([^)]+)\)", index)
        if PurePosixPath(target).parent == PurePosixPath(".")
        and target.endswith(".txt")
    )
    ordered = ("LICENSE", "LICENSES/README.md", *(f"LICENSES/{x}" for x in linked_notices))
    return tuple(dict.fromkeys(ordered))


def _single_root(members: set[str], label: str) -> str:
    roots = {name.split("/", 1)[0] for name in members if name}
    if len(roots) != 1:
        raise ValueError(f"{label} must contain exactly one top-level directory: {sorted(roots)}")
    return next(iter(roots))


def _missing(expected: set[str], actual: set[str], label: str) -> None:
    missing = sorted(expected - actual)
    if missing:
        raise ValueError(f"{label} is missing: {missing}")


def _duplicates(names: list[str], label: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in names:
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    if duplicates:
        raise ValueError(
            f"{label} contains duplicate members: {sorted(duplicates)}"
        )


def _license_assets(
    source_root: Path,
    license_files: tuple[str, ...],
) -> dict[str, bytes]:
    return {
        relative: (source_root / relative).read_bytes() for relative in license_files
    }


def verify_sdist(path: Path, license_assets: dict[str, bytes]) -> dict[str, Any]:
    with tarfile.open(path, "r:gz") as archive:
        member_list = archive.getmembers()
        _duplicates([member.name for member in member_list], "source distribution")
        archive_members = {member.name: member for member in member_list}
        members = set(archive_members)
        root = _single_root(members, "source distribution")
        expected = {f"{root}/{name}" for name in license_assets}
        _missing(expected, members, "source distribution")
        for relative, expected_bytes in license_assets.items():
            member = archive_members[f"{root}/{relative}"]
            if not member.isfile():
                raise ValueError(
                    f"source distribution license asset is not a file: {relative}"
                )
            extracted = archive.extractfile(member)
            if extracted is None or extracted.read() != expected_bytes:
                raise ValueError(
                    f"source distribution license asset differs: {relative}"
                )
    return {
        "file": path.name,
        "sha256": _sha256(path),
        "members": len(members),
        "license_assets": len(license_assets),
        "root": root,
    }


def _source_tree_sha256(source_assets: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for relative, payload in sorted(source_assets.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(payload).digest())
    return digest.hexdigest()


def verify_sdist_source_closure(
    path: Path,
    source_root: Path,
    expected_files: tuple[str, ...],
) -> dict[str, Any]:
    source_assets: dict[str, bytes] = {}
    for relative in expected_files:
        normalized = PurePosixPath(relative)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError(f"invalid repository path: {relative}")
        source_path = source_root.joinpath(*normalized.parts)
        if not source_path.is_file():
            raise ValueError(f"repository source file is missing: {relative}")
        source_assets[normalized.as_posix()] = source_path.read_bytes()

    with tarfile.open(path, "r:gz") as archive:
        member_list = archive.getmembers()
        _duplicates([member.name for member in member_list], "source distribution")
        all_members = {member.name for member in member_list}
        root = _single_root(all_members, "source distribution")
        archive_files = {
            member.name: member for member in member_list if member.isfile()
        }
        expected_archive_files = {
            f"{root}/{relative}" for relative in source_assets
        }
        generated_archive_files = {
            f"{root}/{relative}" for relative in GENERATED_SDIST_FILES
        }
        _missing(
            expected_archive_files,
            set(archive_files),
            "source distribution source closure",
        )
        _missing(
            generated_archive_files,
            set(archive_files),
            "source distribution generated-file closure",
        )
        special_members = sorted(
            member.name
            for member in member_list
            if not member.isfile() and not member.isdir()
        )
        if special_members:
            raise ValueError(
                f"source distribution contains special members: {special_members}"
            )
        unexpected = sorted(
            set(archive_files) - expected_archive_files - generated_archive_files
        )
        if unexpected:
            raise ValueError(
                f"source distribution contains unexpected files: {unexpected}"
            )
        for relative, expected_bytes in source_assets.items():
            member = archive_files[f"{root}/{relative}"]
            extracted = archive.extractfile(member)
            if extracted is None or extracted.read() != expected_bytes:
                raise ValueError(
                    f"source distribution source file differs: {relative}"
                )

    return {
        "expected_files": len(source_assets),
        "generated_files": sorted(GENERATED_SDIST_FILES),
        "source_tree_sha256": _source_tree_sha256(source_assets),
    }


def _git_tracked_files(source_root: Path) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "-C", str(source_root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    return tuple(
        path
        for path in result.stdout.decode("utf-8").split("\0")
        if path
    )


def _runtime_requirements(metadata: bytes) -> list[str]:
    message = email.message_from_bytes(metadata)
    requirements = message.get_all("Requires-Dist", [])
    runtime_requirements = []
    for requirement in requirements:
        _, separator, marker = requirement.partition(";")
        if separator and EXTRA_MARKER_PATTERN.fullmatch(marker.strip()):
            continue
        runtime_requirements.append(requirement)
    return runtime_requirements


def _metadata_message(payload: bytes, label: str) -> Any:
    message = email.message_from_bytes(payload)
    if message.defects:
        raise ValueError(f"{label} contains malformed metadata: {message.defects}")
    return message


def _runtime_source_assets(source_root: Path) -> dict[str, bytes]:
    package_root = source_root / "src" / "sceneio"
    if not package_root.is_dir():
        raise ValueError(f"source package directory is missing: {package_root}")
    assets: dict[str, bytes] = {}
    for path in sorted(item for item in package_root.rglob("*") if item.is_file()):
        if (
            path.suffix.casefold() not in RUNTIME_SOURCE_SUFFIXES
            and path.name not in RUNTIME_SOURCE_NAMES
        ):
            raise ValueError(f"undeclared source-package asset: {path}")
        wheel_path = path.relative_to(source_root / "src").as_posix()
        assets[wheel_path] = path.read_bytes()
    return assets


def _is_native_member(archive: zipfile.ZipFile, name: str) -> bool:
    if NATIVE_NAME_PATTERN.search(PurePosixPath(name).name):
        return True
    with archive.open(name) as stream:
        header = stream.read(8)
    return any(header.startswith(magic) for magic in NATIVE_MAGICS)


def _is_permitted_repaired_library(name: str, platform: str) -> bool:
    return (
        platform == "windows"
        and WINDOWS_REPAIRED_LIBRARY_PATTERN.fullmatch(name) is not None
    )


def _is_expected_delvewheel_metadata(payload: bytes) -> bool:
    try:
        lines = payload.decode("utf-8").rstrip("\r\n").splitlines()
        if (
            len(lines) != 2
            or lines[0] != f"Version: {DELVEWHEEL_VERSION}"
            or not lines[1].startswith("Arguments: ")
        ):
            return False
        arguments = ast.literal_eval(lines[1].removeprefix("Arguments: "))
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return False
    return (
        isinstance(arguments, list)
        and all(isinstance(argument, str) for argument in arguments)
        and len(arguments) >= 3
        and arguments[1] == "repair"
        and "--add-path" in arguments
        and "-w" in arguments
    )


def _is_exact_delvewheel_patched_init(source: bytes, actual: bytes) -> bool:
    future_import = b"from __future__ import annotations"
    lines = source.splitlines(keepends=True)
    matches = [
        index
        for index, line in enumerate(lines)
        if line.rstrip(b"\r\n") == future_import
    ]
    if len(matches) != 1:
        return False
    newline = b"\r\n"
    for index, byte in enumerate(source):
        if byte == 10:
            newline = b"\n"
            break
        if byte == 13:
            newline = (
                b"\r\n"
                if index + 1 < len(source) and source[index + 1] == 10
                else b"\r"
            )
            break
    start_marker = b"# start delvewheel patch"
    end_marker = b"# end delvewheel patch" + newline
    if actual.count(start_marker) != 1 or actual.count(end_marker) != 1:
        return False
    patch_start = actual.index(start_marker)
    patch_end = actual.index(end_marker, patch_start) + len(end_marker)
    patch = actual[patch_start:patch_end]
    normalized_patch = patch.replace(newline, b"\n")
    if (
        hashlib.sha256(normalized_patch).hexdigest()
        != DELVEWHEEL_1_13_0_PATCH_SHA256
    ):
        return False
    future_index = matches[0]
    prefix = b"".join(lines[: future_index + 1]).rstrip()
    remainder = b"".join(lines[future_index + 1 :]).lstrip()
    expected = prefix + newline * 3 + patch
    if remainder:
        expected += newline + remainder
    return actual == expected


def _project_identity(source_root: Path) -> tuple[str, str, str]:
    project_file = source_root / "pyproject.toml"
    project = tomllib.loads(project_file.read_text(encoding="utf-8"))["project"]
    name = project["name"]
    version = project["version"]
    if not isinstance(name, str) or not isinstance(version, str):
        raise ValueError(f"invalid project identity in {project_file}")
    wheel_name = re.sub(r"[-_.]+", "_", name).casefold()
    return name, version, wheel_name


def _wheel_contract(wheel_name: str, source_root: Path) -> WheelContract:
    project_name, project_version, distribution = _project_identity(source_root)
    if not wheel_name.endswith(".whl"):
        raise ValueError(f"invalid wheel filename: {wheel_name}")
    components = wheel_name[:-4].split("-")
    if len(components) != 5:
        raise ValueError(
            f"{wheel_name} must have the exact {distribution}-{project_version}-"
            "cp312-abi3-<platform>.whl shape"
        )
    actual_distribution, version, python_tag, abi_tag, platform_tag = components
    if (
        actual_distribution.casefold() != distribution
        or version != project_version
        or python_tag != "cp312"
        or abi_tag != "abi3"
    ):
        raise ValueError(
            f"{wheel_name} must target {project_name} {project_version} "
            "with cp312-abi3"
        )
    try:
        platform, metadata_tags, core_member = EXPECTED_WHEEL_PLATFORM_TAGS[
            platform_tag.casefold()
        ]
    except KeyError as exc:
        raise ValueError(
            f"unsupported wheel platform tag: {platform_tag}"
        ) from exc
    return WheelContract(platform, metadata_tags, core_member)


def verify_wheel(
    path: Path,
    source_root: Path,
    license_assets: dict[str, bytes],
) -> dict[str, Any]:
    contract = _wheel_contract(path.name, source_root)
    project_name, project_version, distribution = _project_identity(source_root)
    with zipfile.ZipFile(path) as archive:
        member_list = [info.filename for info in archive.infolist() if not info.is_dir()]
        _duplicates(member_list, path.name)
        members = set(member_list)
        metadata_names = sorted(
            name for name in members if name.endswith(".dist-info/METADATA")
        )
        if len(metadata_names) != 1:
            raise ValueError(
                f"{path.name} must contain exactly one METADATA file: {metadata_names}"
            )
        metadata_name = metadata_names[0]
        metadata = archive.read(metadata_name)

        dist_info = metadata_name.removesuffix("/METADATA")
        expected_dist_info = f"{distribution}-{project_version}.dist-info"
        if dist_info != expected_dist_info:
            raise ValueError(
                f"{path.name} must use {expected_dist_info}: {dist_info}"
            )
        metadata_message = _metadata_message(metadata, f"{path.name} METADATA")
        if (
            metadata_message.get_all("Name", []) != [project_name]
            or metadata_message.get_all("Version", []) != [project_version]
        ):
            raise ValueError(
                f"{path.name} METADATA identity must be "
                f"{project_name} {project_version}"
            )
        expected = {
            f"{dist_info}/licenses/{name}" for name in license_assets
        }
        _missing(expected, members, path.name)
        for relative, expected_bytes in license_assets.items():
            member = f"{dist_info}/licenses/{relative}"
            if archive.read(member) != expected_bytes:
                raise ValueError(f"{path.name} license asset differs: {relative}")

        runtime_requirements = _runtime_requirements(metadata)
        if runtime_requirements != EXPECTED_RUNTIME_REQUIREMENTS:
            raise ValueError(
                f"{path.name} must have unconditional NumPy as its sole runtime "
                f"requirement: {runtime_requirements}"
            )

        native_members = sorted(
            name for name in members if _is_native_member(archive, name)
        )
        expected_core_member = contract.core_member
        unexpected_native_members = [
            name
            for name in native_members
            if name != expected_core_member
            and not _is_permitted_repaired_library(name, contract.platform)
        ]
        if (
            expected_core_member not in native_members
            or unexpected_native_members
        ):
            raise ValueError(
                f"{path.name} must contain exactly {expected_core_member} plus "
                "permitted repaired runtime libraries: "
                f"{native_members}"
            )

        runtime_assets = _runtime_source_assets(source_root)
        _missing(set(runtime_assets), members, path.name)
        delvewheel_patched_init = False
        for member, expected_bytes in runtime_assets.items():
            actual_bytes = archive.read(member)
            permitted_patch = (
                contract.platform == "windows"
                and member == "sceneio/__init__.py"
                and _is_exact_delvewheel_patched_init(
                    expected_bytes, actual_bytes
                )
            )
            delvewheel_patched_init = delvewheel_patched_init or permitted_patch
            if actual_bytes != expected_bytes and not permitted_patch:
                raise ValueError(f"{path.name} runtime file differs: {member}")

        delvewheel_member = f"{dist_info}/DELVEWHEEL"
        delvewheel_members: set[str] = set()
        if delvewheel_member in members:
            if (
                contract.platform != "windows"
                or not _is_expected_delvewheel_metadata(
                    archive.read(delvewheel_member)
                )
            ):
                raise ValueError(
                    f"{path.name} contains invalid delvewheel metadata"
                )
            delvewheel_members.add(delvewheel_member)

        repaired_runtime_members = {
            member
            for member in native_members
            if _is_permitted_repaired_library(member, contract.platform)
        }
        repair_components = (
            bool(repaired_runtime_members),
            delvewheel_patched_init,
            bool(delvewheel_members),
        )
        if any(repair_components) and not all(repair_components):
            raise ValueError(
                f"{path.name} contains an incomplete delvewheel repair payload"
            )

        allowed_members = (
            set(runtime_assets)
            | set(native_members)
            | {f"{dist_info}/{name}" for name in WHEEL_METADATA_FILES}
            | delvewheel_members
            | expected
        )
        _missing(
            {f"{dist_info}/{name}" for name in WHEEL_METADATA_FILES},
            members,
            path.name,
        )
        wheel_metadata = _metadata_message(
            archive.read(f"{dist_info}/WHEEL"),
            f"{path.name} WHEEL",
        )
        if wheel_metadata.get_all("Wheel-Version", []) != ["1.0"]:
            raise ValueError(
                f"{path.name} WHEEL must declare Wheel-Version: 1.0 once"
            )
        wheel_tags = tuple(sorted(wheel_metadata.get_all("Tag", [])))
        if wheel_tags != contract.metadata_tags:
            raise ValueError(
                f"{path.name} WHEEL tags must match its filename: "
                f"{wheel_tags} != {contract.metadata_tags}"
            )
        purelib_values = [
            value.strip().casefold()
            for value in wheel_metadata.get_all("Root-Is-Purelib", [])
        ]
        if purelib_values != ["false"]:
            raise ValueError(
                f"{path.name} WHEEL must declare Root-Is-Purelib: false once"
            )
        unexpected_members = sorted(members - allowed_members)
        if unexpected_members:
            raise ValueError(
                f"{path.name} contains unexpected wheel payload: "
                f"{unexpected_members}"
            )

    return {
        "file": path.name,
        "sha256": _sha256(path),
        "members": len(members),
        "license_assets": len(license_assets),
        "platform": contract.platform,
        "wheel_tags": list(wheel_tags),
        "native_members": native_members,
        "runtime_files": len(runtime_assets),
        "runtime_requirements": runtime_requirements,
    }


def verify_distributions(
    source_root: Path,
    sdist: Path,
    wheels: list[Path],
    expected_source_files: tuple[str, ...] | None = None,
    *,
    require_exact_wheel_matrix: bool = False,
) -> dict[str, Any]:
    license_files = _indexed_license_files(source_root)
    license_assets = _license_assets(source_root, license_files)
    if not wheels and expected_source_files is None:
        raise ValueError("at least one wheel or a source-closure check is required")
    source_distribution = verify_sdist(sdist, license_assets)
    wheel_reports = [
        verify_wheel(wheel, source_root, license_assets)
        for wheel in sorted(wheels)
    ]
    platforms = [item["platform"] for item in wheel_reports]
    exact_matrix = ["macos", "manylinux", "windows"]
    if require_exact_wheel_matrix:
        if sorted(platforms) != exact_matrix:
            raise ValueError(
                "wheel set must contain the exact "
                f"three-platform matrix: {platforms}"
            )
    elif (
        platforms
        and len(platforms) != 1
        and sorted(platforms) != exact_matrix
    ):
        raise ValueError(
            "wheel set must contain one platform or the exact "
            f"three-platform matrix: {platforms}"
        )
    report = {
        "source_distribution": source_distribution,
        "wheels": wheel_reports,
    }
    if expected_source_files is not None:
        report["source_closure"] = verify_sdist_source_closure(
            sdist,
            source_root,
            expected_source_files,
        )
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--wheel-dir", type=Path)
    parser.add_argument("--require-git-source-closure", action="store_true")
    parser.add_argument("--require-exact-wheel-matrix", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    wheels = [] if args.wheel_dir is None else sorted(args.wheel_dir.glob("*.whl"))
    expected_source_files = (
        _git_tracked_files(args.source_root)
        if args.require_git_source_closure
        else None
    )
    report = verify_distributions(
        args.source_root,
        args.sdist,
        wheels,
        expected_source_files,
        require_exact_wheel_matrix=args.require_exact_wheel_matrix,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
