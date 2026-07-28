"""Tests for deterministic Windows wheel runtime repair."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "repair_windows_wheel.py"
SPEC = importlib.util.spec_from_file_location("repair_windows_wheel", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
REPAIR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPAIR)


def _redist(
    root: Path,
    *,
    version: str = "14.44.35211",
    payload: bytes = b"visual-studio-msvcp",
) -> Path:
    path = (
        root
        / "Microsoft Visual Studio"
        / "2022"
        / "BuildTools"
        / "VC"
        / "Redist"
        / "MSVC"
        / version
        / "x64"
        / "Microsoft.VC143.CRT"
    )
    path.mkdir(parents=True)
    (path / "msvcp140.dll").write_bytes(payload)
    return path


def _wheel(path: Path, payload: bytes, member: str = "sceneio.libs/msvcp140.dll") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, payload)


def test_find_vc143_redist_selects_latest_version(tmp_path: Path) -> None:
    program_files = tmp_path / "Program Files (x86)"
    _redist(program_files, version="14.38.33135")
    expected = _redist(program_files, version="14.44.35211")

    actual = REPAIR.find_vc143_redist({"ProgramFiles(x86)": str(program_files)})

    assert actual == expected.resolve()


def test_find_vc143_redist_accepts_configured_toolchain(tmp_path: Path) -> None:
    configured = tmp_path / "VC" / "Redist" / "MSVC" / "14.44.35211"
    expected = configured / "x64" / "Microsoft.VC143.CRT"
    expected.mkdir(parents=True)
    (expected / "msvcp140.dll").write_bytes(b"runtime")

    actual = REPAIR.find_vc143_redist({"VCToolsRedistDir": str(configured)})

    assert actual == expected.resolve()


def test_verify_repaired_wheel_requires_exact_redist_bytes(tmp_path: Path) -> None:
    redist = _redist(tmp_path)
    payload = (redist / "msvcp140.dll").read_bytes()
    wheel = tmp_path / "sceneio.whl"
    _wheel(wheel, payload)

    report = REPAIR.verify_repaired_wheel(wheel, redist)

    assert report["vc_redist_dir"] == str(redist)
    assert report["libraries"] == [
        {
            "member": "sceneio.libs/msvcp140.dll",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "source": str(redist / "msvcp140.dll"),
        }
    ]

    _wheel(wheel, b"different")
    with pytest.raises(RuntimeError, match="differs from Visual Studio"):
        REPAIR.verify_repaired_wheel(wheel, redist)


def test_verify_repaired_wheel_rejects_name_mangling(tmp_path: Path) -> None:
    redist = _redist(tmp_path)
    wheel = tmp_path / "sceneio.whl"
    _wheel(
        wheel,
        (redist / "msvcp140.dll").read_bytes(),
        "sceneio.libs/msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll",
    )

    with pytest.raises(RuntimeError, match="no repaired MSVC runtime"):
        REPAIR.verify_repaired_wheel(wheel, redist)


def test_repair_wheel_prioritizes_redist_and_disables_mangling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program_files = tmp_path / "Program Files (x86)"
    redist = _redist(program_files)
    source = tmp_path / "input.whl"
    source.write_bytes(b"input")
    dest = tmp_path / "repaired"
    observed: dict[str, object] = {}

    def fake_run(
        command: list[str],
        *,
        check: bool,
        env: dict[str, str],
    ) -> None:
        observed.update(command=command, check=check, env=env)
        _wheel(dest / "sceneio.whl", (redist / "msvcp140.dll").read_bytes())

    monkeypatch.setattr(REPAIR.subprocess, "run", fake_run)
    monkeypatch.setattr(
        REPAIR.os,
        "environ",
        {
            "ProgramFiles(x86)": str(program_files),
            "PATH": "runner-path",
        },
    )

    REPAIR.repair_wheel(source, dest)

    command = observed["command"]
    assert isinstance(command, list)
    assert command[:6] == [
        REPAIR.sys.executable,
        "-m",
        "delvewheel",
        "repair",
        "--add-path",
        str(redist.resolve()),
    ]
    for runtime in REPAIR.RUNTIME_BASENAMES:
        index = command.index(runtime)
        assert command[index - 1] == "--no-mangle"
    assert command[-3:] == ["-w", str(dest), str(source)]
    environment = observed["env"]
    assert isinstance(environment, dict)
    assert environment["PATH"] == str(redist.resolve()) + os.pathsep + "runner-path"
    assert observed["check"] is True
