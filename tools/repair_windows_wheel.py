"""Repair a Windows wheel from the Visual Studio redistributable directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

RUNTIME_DIRECTORY = "Microsoft.VC143.CRT"
RUNTIME_BASENAMES = frozenset(
    {
        "concrt140.dll",
        "msvcp140.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
    }
)
SIDECAR_PATTERN = re.compile(
    r"sceneio\.libs/"
    r"(?P<stem>concrt140|msvcp140|vcruntime140|vcruntime140_1)"
    r"\.dll",
    re.IGNORECASE,
)


def _version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", path.parent.parent.name))


def find_vc143_redist(environ: Mapping[str, str]) -> Path:
    candidates: set[Path] = set()
    if configured := environ.get("VCToolsRedistDir"):
        configured_path = Path(configured)
        candidates.add(configured_path / "x64" / RUNTIME_DIRECTORY)
        candidates.add(configured_path / RUNTIME_DIRECTORY)
        if configured_path.name == RUNTIME_DIRECTORY:
            candidates.add(configured_path)

    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        if root := environ.get(variable):
            visual_studio = (
                Path(root)
                / "Microsoft Visual Studio"
                / "2022"
            )
            candidates.update(
                visual_studio.glob(
                    f"*/VC/Redist/MSVC/*/x64/{RUNTIME_DIRECTORY}"
                )
            )

    valid = sorted(
        {
            candidate.resolve()
            for candidate in candidates
            if (candidate / "msvcp140.dll").is_file()
        },
        key=lambda path: (_version_key(path), path.as_posix().casefold()),
    )
    if not valid:
        raise RuntimeError("Visual Studio VC143 x64 redistributable not found")
    return valid[-1]


def verify_repaired_wheel(wheel: Path, redist_dir: Path) -> dict[str, object]:
    with zipfile.ZipFile(wheel) as archive:
        members = [
            info.filename
            for info in archive.infolist()
            if not info.is_dir() and SIDECAR_PATTERN.fullmatch(info.filename)
        ]
        if not members:
            raise RuntimeError(f"{wheel.name} has no repaired MSVC runtime")

        libraries = []
        for member in sorted(members):
            match = SIDECAR_PATTERN.fullmatch(member)
            assert match is not None
            source_name = f"{match.group('stem')}.dll".casefold()
            if source_name not in RUNTIME_BASENAMES:
                raise RuntimeError(f"unexpected repaired runtime: {member}")
            source = redist_dir / source_name
            if not source.is_file():
                raise RuntimeError(f"missing Visual Studio source for {member}")
            source_bytes = source.read_bytes()
            wheel_bytes = archive.read(member)
            if wheel_bytes != source_bytes:
                raise RuntimeError(
                    f"{member} differs from Visual Studio redistributable"
                )
            libraries.append(
                {
                    "member": member,
                    "sha256": hashlib.sha256(wheel_bytes).hexdigest(),
                    "source": str(source),
                }
            )

    return {
        "repaired_wheel": str(wheel),
        "vc_redist_dir": str(redist_dir),
        "libraries": libraries,
    }


def repair_wheel(wheel: Path, dest_dir: Path) -> dict[str, object]:
    redist_dir = find_vc143_redist(os.environ)
    dest_dir.mkdir(parents=True, exist_ok=True)
    before = set(dest_dir.glob("*.whl"))
    environment = dict(os.environ)
    environment["PATH"] = str(redist_dir) + os.pathsep + environment.get("PATH", "")
    command = [
        sys.executable,
        "-m",
        "delvewheel",
        "repair",
        "--add-path",
        str(redist_dir),
    ]
    for runtime in sorted(RUNTIME_BASENAMES):
        command.extend(("--no-mangle", runtime))
    command.extend(("-w", str(dest_dir), str(wheel)))
    subprocess.run(
        command,
        check=True,
        env=environment,
    )
    produced = set(dest_dir.glob("*.whl")) - before
    if len(produced) != 1:
        raise RuntimeError(f"repair must produce exactly one wheel: {sorted(produced)}")
    return verify_repaired_wheel(produced.pop(), redist_dir)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--dest-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    print(json.dumps(repair_wheel(args.wheel, args.dest_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
